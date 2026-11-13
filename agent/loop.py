"""The agent loop (ReAct): model decides -> tool runs -> result goes back -> repeat -> final answer.

Safety built in:
  * max_steps stops endless loops
  * tool errors are returned to the model as readable text; temporary errors retry up to 2 times
  * sensitive tools (add_reminder) PAUSE for the student's approval
  * tool results are wrapped as DATA, so text inside them cannot act as instructions
  * unknown tool names / bad arguments are counted as invalid tool calls
"""
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from tools.db import ToolError, TransientToolError

MAX_RETRIES = 2
HISTORY_LIMIT = 10      # short-term memory: last N chat messages


@dataclass
class Step:
    n: int
    kind: str                 # tool_call | tool_result | tool_error | invalid_tool_call | approval | final
    name: str = None
    arguments: dict = None
    result: object = None
    seconds: float = 0.0


@dataclass
class AgentResult:
    status: str               # ok | awaiting_approval | step_limit | model_error
    final: dict = None        # {"answer","sources","caveats"}
    steps: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    pending: dict = None      # {"name","arguments"} when awaiting approval
    model_calls: int = 0
    invalid_tool_calls: int = 0
    format_ok: bool = True
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})
    seconds: float = 0.0

    @property
    def tool_sequence(self):
        return [s.name for s in self.steps if s.kind == "tool_call"]


def wrap_tool_result(name, payload):
    """Mark tool output as data. Closing tags inside the text are neutralised."""
    body = json.dumps(payload, ensure_ascii=False, default=str).replace("</tool_result>", "<\\/tool_result>")
    return f'<tool_result name="{name}">\n{body}\n</tool_result>'


def parse_final(content):
    """Expect {"answer","sources","caveats"}. Falls back to plain text and flags it."""
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "answer" in data:
            return {"answer": str(data["answer"]), "sources": list(data.get("sources") or []),
                    "caveats": list(data.get("caveats") or [])}, True
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return {"answer": content or "", "sources": [],
            "caveats": ["The model did not use the required JSON answer format."]}, False


class Agent:
    def __init__(self, model, registry, system_prompt, user_id, max_steps=8,
                 approval_mode="ask", log_path=None):
        """approval_mode: 'ask' = pause and return awaiting_approval; 'auto_yes' / 'auto_no' for tests."""
        self.model, self.registry, self.system_prompt = model, registry, system_prompt
        self.user_id, self.max_steps = user_id, max_steps
        self.approval_mode, self.log_path = approval_mode, log_path

    # ---------- public ----------
    def start(self, user_message, history=None):
        msgs = [{"role": "system", "content": self.system_prompt}]
        msgs += [m for m in (history or []) if m["role"] in ("user", "assistant")][-HISTORY_LIMIT:]
        msgs.append({"role": "user", "content": user_message})
        return self._loop(AgentResult(status="ok", messages=msgs), user_message)

    def resume(self, result, approved):
        """Continue after the student answered an approval request."""
        if result.status != "awaiting_approval" or not result.pending:
            raise ValueError("Nothing is waiting for approval.")
        pending, result.pending, result.status = result.pending, None, "ok"
        self._execute(result, pending["name"], pending["arguments"], approved=bool(approved))
        return self._loop(result, None)

    # ---------- internals ----------
    def _loop(self, r, user_message):
        t0 = time.time()
        schemas = self.registry.schemas()
        while True:
            if r.model_calls >= self.max_steps:
                r.status = "step_limit"
                r.final = {"answer": "I could not finish this within the allowed number of steps.",
                           "sources": [], "caveats": ["step limit reached"]}
                break
            try:
                reply = self.model.generate(r.messages, schemas)
            except Exception as e:                      # model/API failure
                r.status = "model_error"
                r.final = {"answer": "The model could not be reached.", "sources": [],
                           "caveats": [f"model error: {e}"]}
                break
            r.model_calls += 1
            for k in ("input_tokens", "output_tokens"):
                r.usage[k] += int((reply.usage or {}).get(k, 0))
            bad = (reply.usage or {}).get("rejected_tool_call")
            if bad:                     # model wrapped its answer in a made-up tool call
                r.invalid_tool_calls += 1
                r.steps.append(Step(len(r.steps) + 1, "invalid_tool_call", bad, None,
                                    "Answer was sent as a call to a tool that does not exist; answer kept."))
            if reply.kind == "final":
                r.final, r.format_ok = parse_final(reply.content)
                r.steps.append(Step(len(r.steps) + 1, "final", result=r.final))
                r.messages.append({"role": "assistant", "content": reply.content})
                r.status = "ok"
                break
            r.messages.append({"role": "assistant", "tool_call": {"name": reply.name, "arguments": reply.arguments},
                               "raw": getattr(reply, "raw", None)})
            self._execute(r, reply.name, reply.arguments)
            if r.status == "awaiting_approval":
                break
        r.seconds += time.time() - t0
        self._log(r, user_message)
        return r

    def _execute(self, r, name, args, approved=None):
        args = dict(args or {})
        tool = self.registry.get(name)
        if tool is None:
            r.invalid_tool_calls += 1
            msg = f"Unknown tool '{name}'. Available tools: {sorted(self.registry.tools)}."
            r.steps.append(Step(len(r.steps) + 1, "invalid_tool_call", name, args, msg))
            r.messages.append({"role": "tool", "name": name or "unknown", "content": wrap_tool_result(name, {"error": msg})})
            return
        problem = self.registry.validate(tool, args)
        if problem:
            r.invalid_tool_calls += 1
            r.steps.append(Step(len(r.steps) + 1, "invalid_tool_call", name, args, problem))
            r.messages.append({"role": "tool", "name": name, "content": wrap_tool_result(name, {"error": problem})})
            return
        if approved is None:                        # not a resume after approval
            r.steps.append(Step(len(r.steps) + 1, "tool_call", name, args))
        if tool.needs_approval:
            decision = approved
            if decision is None:
                decision = {"auto_yes": True, "auto_no": False}.get(self.approval_mode)
            if decision is None:
                r.status, r.pending = "awaiting_approval", {"name": name, "arguments": args}
                r.steps.append(Step(len(r.steps) + 1, "approval", name, args, "waiting for the student"))
                return
            r.steps.append(Step(len(r.steps) + 1, "approval", name, args, "approved" if decision else "denied"))
            if not decision:
                r.messages.append({"role": "tool", "name": name, "content": wrap_tool_result(
                    name, {"error": "The student did NOT approve this action. Nothing was saved. Tell the student."})})
                return
        if tool.needs_user_id:
            args["user_id"] = self.user_id          # the model can never act for another student
        t0, attempt, payload, kind = time.time(), 0, None, "tool_result"
        while True:
            try:
                payload = tool.func(**args)
                break
            except TransientToolError as e:
                attempt += 1
                if attempt > MAX_RETRIES:
                    payload, kind = {"error": f"Temporary failure after retries: {e}"}, "tool_error"
                    break
            except ToolError as e:
                payload, kind = {"error": str(e)}, "tool_error"
                break
            except Exception as e:                  # never crash the loop on a tool bug
                payload, kind = {"error": f"Tool failed unexpectedly: {type(e).__name__}: {e}"}, "tool_error"
                break
        r.steps.append(Step(len(r.steps) + 1, kind, name, None, payload, time.time() - t0))
        r.messages.append({"role": "tool", "name": name, "content": wrap_tool_result(name, payload)})

    def _log(self, r, user_message):
        if not self.log_path:
            return
        entry = {"time": datetime.now().isoformat(timespec="seconds"),
                 "model": getattr(self.model, "name", type(self.model).__name__),
                 "user_message": user_message, "status": r.status, "model_calls": r.model_calls,
                 "invalid_tool_calls": r.invalid_tool_calls, "usage": r.usage,
                 "seconds": round(r.seconds, 3), "format_ok": r.format_ok,
                 "steps": [{"n": s.n, "kind": s.kind, "name": s.name, "arguments": s.arguments,
                            "seconds": round(s.seconds, 3)} for s in r.steps],
                 "final": r.final}
        p = Path(self.log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_system_prompt(path=None):
    path = Path(path or Path(__file__).resolve().parent.parent / "prompts" / "system_v2.md")
    return path.read_text(encoding="utf-8")
