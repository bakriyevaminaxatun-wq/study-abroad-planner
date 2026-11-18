"""Test runner: sends the 24 test tasks to each model and saves one log line per task.

Every model gets exactly the same setup: the same SYNTHETIC test data (fake scholarships
Alpha, Beta, Gamma...), the same fake student profiles, the same prompt (v3), the same tools,
the same step limit and the same fixed "today" date. So the results can be compared fairly.

Run (from the project folder, with .venv active):
    python -m eval.run_tests --models openai/gpt-oss-20b --tasks T05,T07     # quick check, 2 tasks
    python -m eval.run_tests --models all                                     # everything

Results go to results/runs/<model>.jsonl (one JSON line per task).
Tasks that are already in that file are skipped, so you can stop (Ctrl+C) and continue later.
If a provider's free quota runs out, nothing is saved for that task (it is not the model's fault);
the runner moves on to the next model, and the same command later continues where it stopped.
Old results that ended in a model error are run again.
Use --fresh to delete the old results of the chosen models and start again.
"""
import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

import load_sheet                                         # noqa: E402
from agent.loop import Agent, load_system_prompt          # noqa: E402
from agent.models import MODELS, available_models, make_model   # noqa: E402
from agent.registry import build_default_registry         # noqa: E402
from tests.conftest import make_sheet                     # noqa: E402  (the synthetic sheet)
from tools import guidance                                # noqa: E402
from tools.profile import update_user_profile             # noqa: E402

TODAY = date(2026, 11, 12)     # fixed date the test set was written for
MAX_STEPS = 8
PROMPT_FILE = ROOT / "prompts" / "system_v3.md"
TEST_SET = ROOT / "tests" / "test_set.json"
OUT_DIR = ROOT / "results" / "runs"


def is_quota_error(rec):
    """Free-tier quota, rate limit or an overloaded server that did not clear after the waits:
    not the model's fault."""
    if rec["status"] != "model_error":
        return False
    text = " ".join((rec.get("final") or {}).get("caveats", [])).lower()
    return any(w in text for w in ("429", "quota", "rate limit", "resource_exhausted",
                                    "503", "over capacity", "overloaded", "unavailable"))


def load_done(path):
    """Task ids already finished. Lines that ended in a model error are removed, so they run again."""
    if not path.exists():
        return set()
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    keep = [l for l in lines if json.loads(l)["status"] != "model_error"]
    if len(keep) != len(lines):
        path.write_text("".join(l + "\n" for l in keep), encoding="utf-8")
        print(f"Removed {len(lines) - len(keep)} old result(s) that ended in a model error; they will run again.")
    return {json.loads(l)["task_id"] for l in keep}


PRICES = json.loads((Path(__file__).parent / "prices.json").read_text(encoding="utf-8"))


def task_cost(rec):
    """Paid-tier price of this task's tokens in USD (None if the price is unknown)."""
    p = PRICES.get(rec["model"])
    if not p:
        return None
    u = rec.get("usage") or {}
    return (u.get("input_tokens", 0) * p["input"] + u.get("output_tokens", 0) * p["output"]) / 1_000_000


def safe_name(model_id):
    return model_id.replace("/", "_").replace(":", "_")


class Workspace:
    """Temporary folder with the synthetic data and the guidance search databases."""

    def __init__(self, test_set, embedder):
        self.dir = Path(tempfile.mkdtemp(prefix="sap_eval_"))
        self.test_set, self.embedder = test_set, embedder
        fx = test_set["fixtures"]
        # guidance search: normal and "poisoned" (one extra file with an injected instruction)
        self.chroma = self.dir / "chroma_clean"
        guidance.ingest(guidance.GUIDANCE_DIR, self.chroma, embedder)
        poisoned_dir = self.dir / "guidance_poisoned"
        shutil.copytree(guidance.GUIDANCE_DIR, poisoned_dir)
        pg = fx["poisoned_guidance"]
        (poisoned_dir / pg["file"]).write_text(pg["text"], encoding="utf-8")
        self.chroma_poisoned = self.dir / "chroma_poisoned"
        guidance.ingest(poisoned_dir, self.chroma_poisoned, embedder)

    def fresh_database(self, task, n):
        """A new database for every task, so one task cannot affect another."""
        note = None
        if task.get("fixture") == "poisoned_scholarship_note":
            note = self.test_set["fixtures"]["poisoned_scholarship_note"]["text"]
        sheet = self.dir / f"sheet_{n}.xlsx"
        db, rates = self.dir / f"db_{n}.sqlite", self.dir / f"rates_{n}.json"
        make_sheet(sheet, poisoned_note=note)
        load_sheet.load(sheet, db, rates)
        self._add_profile(task["profile_id"], db)
        return db, rates

    def _add_profile(self, profile_id, db):
        p = self.test_set["profiles"][profile_id]
        uid = p["user_id"]
        update_user_profile(uid, {k: p[k] for k in ("field_of_study", "gpa", "english_level",
                                                    "target_countries", "savings_azn",
                                                    "monthly_saving_azn")}, db_path=db, today=TODAY)
        how_many = int(p["chosen_applications"].split()[1])      # "first 3 verified scholarships"
        con = sqlite3.connect(db)
        ids = [r[0] for r in con.execute("SELECT id FROM scholarships ORDER BY id")][:how_many]
        con.close()
        for sid in ids:
            update_user_profile(uid, {"add_chosen_application": sid}, db_path=db, today=TODAY)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def count_reminders(db):
    con = sqlite3.connect(db)
    n = con.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
    con.close()
    return n


def step_to_dict(s):
    return {"n": s.n, "kind": s.kind, "name": s.name, "arguments": s.arguments,
            "result": s.result, "seconds": round(s.seconds, 3)}


def run_task(model, task, ws, n, prompt):
    db, rates = ws.fresh_database(task, n)
    chroma = ws.chroma_poisoned if task.get("fixture") == "poisoned_guidance" else ws.chroma
    registry = build_default_registry(db_path=db, rates_path=rates, today=TODAY,
                                      chroma_dir=chroma, embedder=ws.embedder)
    uid = ws.test_set["profiles"][task["profile_id"]]["user_id"]
    agent = Agent(model, registry, prompt, uid, max_steps=MAX_STEPS, approval_mode="ask")
    rejected_before = getattr(model, "rejected_tool_calls", 0)
    waited_before = getattr(model, "waited_seconds", 0.0)
    t0 = time.time()
    result = agent.start(task["user_message"])
    approval = None
    if result.status == "awaiting_approval":
        # the agent paused before saving: check nothing was saved yet, then "the student" approves
        approval = {"paused": True, "tool": result.pending["name"],
                    "arguments": result.pending["arguments"],
                    "reminders_saved_before_approval": count_reminders(db)}
        result = agent.resume(result, approved=True)
    seconds = time.time() - t0
    waited = getattr(model, "waited_seconds", 0.0) - waited_before
    return {
        "time": datetime.now().isoformat(timespec="seconds"),
        "model": model.name, "model_type": MODELS.get(model.name, ("", "?"))[1],
        "prompt_version": PROMPT_FILE.stem,
        "task_id": task["id"], "language": task["language"], "category": task["category"],
        "user_message": task["user_message"],
        "expected_tool_sequence": task["expected_tool_sequence"], "checks": task["checks"],
        "status": result.status,
        "tool_sequence": result.tool_sequence,
        "model_calls": result.model_calls,
        "invalid_tool_calls": result.invalid_tool_calls,
        "rejected_tool_calls": getattr(model, "rejected_tool_calls", 0) - rejected_before,
        "format_ok": result.format_ok,
        "approval": approval,
        "reminders_saved": count_reminders(db),
        "usage": result.usage,
        "seconds": round(seconds, 2),
        "seconds_waiting_for_rate_limit": round(waited, 2),
        "final": result.final,
        "steps": [step_to_dict(s) for s in result.steps],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="all", help="'all' or model ids separated by commas")
    ap.add_argument("--tasks", default="", help="task ids separated by commas, e.g. T05,T07 (default: all 24)")
    ap.add_argument("--fresh", action="store_true", help="delete old results of these models first")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--fake-embedder", action="store_true", help="offline word-hash embedder (for code tests only)")
    args = ap.parse_args(argv)

    test_set = json.loads(TEST_SET.read_text(encoding="utf-8"))
    tasks = test_set["tasks"]
    if args.tasks:
        wanted = [t.strip().upper() for t in args.tasks.split(",") if t.strip()]
        unknown = set(wanted) - {t["id"] for t in tasks}
        if unknown:
            sys.exit(f"Unknown task id(s): {sorted(unknown)}")
        tasks = [t for t in tasks if t["id"] in wanted]

    avail = available_models()
    model_ids = avail if args.models == "all" else [m.strip() for m in args.models.split(",")]
    missing = [m for m in model_ids if m not in avail]
    if missing:
        sys.exit(f"No API key in .env for: {missing}. Available: {avail}")
    if not model_ids:
        sys.exit("No models available. Add GEMINI_API_KEY and/or GROQ_API_KEY to .env.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    embedder = guidance.HashEmbedder() if args.fake_embedder else guidance.E5Embedder()
    print("Preparing test data and guidance search (first time can take a minute)...")
    ws = Workspace(test_set, embedder)
    prompt = PROMPT_FILE.read_text(encoding="utf-8")
    try:
        for mid in model_ids:
            path = out_dir / f"{safe_name(mid)}.jsonl"
            if args.fresh and path.exists():
                path.unlink()
            done = load_done(path)
            todo = [t for t in tasks if t["id"] not in done]
            print(f"\n=== {mid}: {len(todo)} task(s) to run, {len(done)} already done ===")
            model = make_model(mid)
            total_cost = 0.0
            for i, task in enumerate(todo, 1):
                rec = run_task(model, task, ws, f"{safe_name(mid)}_{task['id']}", prompt)
                if is_quota_error(rec):
                    print(f"[{i}/{len(todo)}] {task['id']}: {mid} free quota is used up -> NOT saved. "
                          f"Moving to the next model. Run the same command later to finish {mid}.")
                    break
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                tools = " > ".join(rec["tool_sequence"]) or "(no tools)"
                cost = task_cost(rec)
                total_cost += cost or 0.0
                u = rec.get("usage") or {}
                money = f"  ${cost:.4f} (total ${total_cost:.3f})" if cost is not None else ""
                print(f"[{i}/{len(todo)}] {task['id']} {task['language']} {task['category']:<9} "
                      f"{rec['status']:<11} {rec['seconds']:>6.1f}s  tokens {u.get('input_tokens', 0)}/"
                      f"{u.get('output_tokens', 0)}{money}  tools: {tools}")
                if rec["status"] == "model_error":
                    print("      error:", "; ".join(rec["final"].get("caveats", []))[:300])
            print(f"Saved: {path}")
    except KeyboardInterrupt:
        print("\nStopped. Finished tasks are saved; run the same command again to continue.")
    finally:
        ws.cleanup()


if __name__ == "__main__":
    main()
