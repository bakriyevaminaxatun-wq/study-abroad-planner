"""Tiny, cheap check: does Claude receive our tool results? (about 4 short requests, well under $0.01)

Run:  python -m eval.check_claude_tools              (4 tiny requests)
      python -m eval.check_claude_tools --task T07   (one real task, max 3 requests, ~$0.02)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.models import make_model   # noqa: E402

MODEL = "claude-sonnet-5-5"
TOOLS = [{"type": "function", "function": {
    "name": "get_number", "description": "Returns the secret number.",
    "parameters": {"type": "object", "properties": {}, "required": []}}}]
BASE = [{"role": "system", "content": "Use get_number, then reply with only the number."},
        {"role": "user", "content": "What is the secret number?"}]

m = make_model(MODEL)
client = m.client
used = [0, 0]


def ask(messages):
    r = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS, max_tokens=50)
    if r.usage:
        used[0] += r.usage.prompt_tokens or 0
        used[1] += r.usage.completion_tokens or 0
    return r.choices[0].message, r.usage


if "--task" not in sys.argv:
    first, u = ask(BASE)
    print("1) First reply, as received:")
    print("  ", json.dumps(first.model_dump(exclude_none=True), ensure_ascii=False)[:600])
    print("   input tokens:", u.prompt_tokens if u else "?")
    if not first.tool_calls:
        sys.exit("Claude did not call the tool, so there is nothing to check. Paste this output to Claude.")
    tc = first.tool_calls[0].model_dump(exclude_none=True)
    result = {"role": "tool", "tool_call_id": tc["id"], "content": "42"}

    variants = {
        "A (our current format: no content key)": {"role": "assistant", "tool_calls": [tc]},
        "B (content: null)": {"role": "assistant", "content": None, "tool_calls": [tc]},
        "C (Claude's own message, unchanged)": {**first.model_dump(exclude_none=True), "role": "assistant"},
    }
    print("\n2) Sending the tool result (42) back in 3 formats:")
    for name, assistant_msg in variants.items():
        try:
            reply, u = ask(BASE + [assistant_msg, result])
            got = "called the tool AGAIN (did not see the result)" if reply.tool_calls else repr(reply.content)
            print(f"   {name}: {got}   [input tokens: {u.prompt_tokens if u else '?'}]")
        except Exception as e:                                    # noqa: BLE001
            print(f"   {name}: ERROR {str(e)[:300]}")

    cost = (used[0] * 2.00 + used[1] * 10.00) / 1_000_000
    print(f"\nTotal tokens: {used[0]} in / {used[1]} out  ->  about ${cost:.4f}")


# ---------------------------------------------------------------------------------------------
# Part 2 (only with --task): run ONE real test task with a hard limit of 3 model calls and print
# every raw reply, to see why the model repeats a tool. About 3 requests of ~3,000 tokens (~$0.02).
if "--task" in sys.argv:
    from eval import run_tests
    from tools import guidance
    task_id = sys.argv[sys.argv.index("--task") + 1].upper()
    data = json.loads(run_tests.TEST_SET.read_text(encoding="utf-8"))
    task = next(t for t in data["tasks"] if t["id"] == task_id)
    run_tests.MAX_STEPS = 3                                  # hard cap: at most 3 paid requests
    real_create = client.chat.completions.create

    def spy(**kw):
        r = real_create(**kw)
        msg, n = r.choices[0], len(kw["messages"])
        print(f"\n--- request with {n} messages -> finish_reason={msg.finish_reason}, "
              f"input tokens={r.usage.prompt_tokens if r.usage else '?'}")
        print("    last message sent:", json.dumps(kw["messages"][-1], ensure_ascii=False, default=str)[:300])
        print("    reply:", json.dumps(msg.message.model_dump(exclude_none=True), ensure_ascii=False)[:700])
        if r.usage:
            used[0] += r.usage.prompt_tokens or 0
            used[1] += r.usage.completion_tokens or 0
        return r

    client.chat.completions.create = spy
    ws = run_tests.Workspace(data, guidance.HashEmbedder())
    try:
        rec = run_tests.run_task(m, task, ws, "check", run_tests.PROMPT_FILE.read_text(encoding="utf-8"))
    finally:
        ws.cleanup()
    print(f"\nStatus: {rec['status']}; tools: {rec['tool_sequence']}")
    cost = (used[0] * 2.00 + used[1] * 10.00) / 1_000_000
    print(f"Total for this check: {used[0]} in / {used[1]} out  ->  about ${cost:.4f}")
