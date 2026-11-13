"""Checks the test runner end to end with a scripted fake model (no internet, no API quota)."""
import json

import pytest

from agent.models import ScriptedModel, call, final
from eval import run_tests
from tools import guidance

DATA = json.loads(run_tests.TEST_SET.read_text(encoding="utf-8"))
TASK = {t["id"]: t for t in DATA["tasks"]}


@pytest.fixture(scope="module")
def ws():
    w = run_tests.Workspace(DATA, guidance.HashEmbedder())
    yield w
    w.cleanup()


def test_profile_and_chosen_applications_are_set_up(ws):
    db, _ = ws.fresh_database(TASK["T07"], "p")
    from tools.profile import get_user_profile
    p = get_user_profile("test_user_1", db_path=db)
    assert p["profile"]["field_of_study"] == "Computer Science"
    assert [a["scholarship_id"] for a in p["chosen_applications"]] == [1, 2, 3]


def test_simple_task_is_logged(ws):
    model = ScriptedModel([call("search_scholarships", country="Germany"),
                           final("Alpha.", sources=["https://example.org/alpha"])])
    model.name = "scripted"
    rec = run_tests.run_task(model, TASK["T05"], ws, "s1", "system")
    assert rec["status"] == "ok" and rec["tool_sequence"] == ["search_scholarships"]
    assert rec["final"]["answer"] == "Alpha." and rec["approval"] is None
    assert rec["steps"][1]["result"]["count"] >= 1          # tool results are saved for the checks
    json.dumps(rec, default=str)                            # can be written as one JSON line


def test_approval_pauses_before_saving_then_continues(ws):
    model = ScriptedModel([call("add_reminder", text="Book IELTS", date="2026-12-01"),
                           final("Saved.")])
    model.name = "scripted"
    rec = run_tests.run_task(model, TASK["T18"], ws, "s2", "system")
    assert rec["approval"]["paused"] and rec["approval"]["reminders_saved_before_approval"] == 0
    assert rec["reminders_saved"] == 1 and rec["status"] == "ok"


def test_poisoned_fixtures_are_applied(ws):
    db, _ = ws.fresh_database(TASK["T24"], "f1")
    import sqlite3
    notes = " ".join(r[0] or "" for r in sqlite3.connect(db).execute("SELECT notes FROM scholarships"))
    assert "SYSTEM:" in notes
    hits = guidance.search_guidance("IELTS tips", persist_dir=ws.chroma_poisoned, embedder=ws.embedder, k=10)
    assert any("SYSTEM INSTRUCTION" in p["text"] for p in hits["passages"])
    clean = guidance.search_guidance("IELTS tips", persist_dir=ws.chroma, embedder=ws.embedder, k=10)
    assert not any("SYSTEM INSTRUCTION" in p["text"] for p in clean["passages"])
