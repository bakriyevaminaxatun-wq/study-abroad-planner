"""Checks the real-model connector without calling the internet (a fake client stands in)."""
import json
from types import SimpleNamespace as NS

from agent.loop import Agent
from agent.models import OpenAICompatModel
from agent.registry import build_default_registry


import pytest


@pytest.fixture()
def registry(env):
    return build_default_registry(db_path=env["db"], rates_path=env["rates"])


class FakeClient:
    """Answers like the OpenAI API: first a tool call, then a final JSON answer."""
    def __init__(self):
        self.sent = []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, model, messages, tools, temperature):
        self.sent.append(messages)
        usage = NS(prompt_tokens=10, completion_tokens=5)
        if len(self.sent) == 1:
            call = NS(function=NS(name="search_scholarships", arguments='{"country": "Germany"}'))
            return NS(choices=[NS(message=NS(tool_calls=[call], content=None))], usage=usage)
        final = json.dumps({"answer": "Found DAAD.", "sources": ["https://daad.de"], "caveats": []})
        return NS(choices=[NS(message=NS(tool_calls=None, content=final))], usage=usage)


def test_message_conversion_links_tool_results_to_calls():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"},
            {"role": "assistant", "tool_call": {"name": "get_user_profile", "arguments": {}}},
            {"role": "tool", "name": "get_user_profile", "content": "<tool_result/>"}]
    out = OpenAICompatModel.to_api_messages(msgs)
    assert out[2]["tool_calls"][0]["id"] == out[3]["tool_call_id"] == "call_1"
    assert out[3]["role"] == "tool"


def test_agent_runs_with_real_model_class(registry):
    client = FakeClient()
    model = OpenAICompatModel("fake-model", "key", client=client)
    r = Agent(model, registry, "system", "u1").start("DAAD?")
    assert r.status == "ok" and r.final["answer"] == "Found DAAD."
    assert r.tool_sequence == ["search_scholarships"]
    assert r.usage == {"input_tokens": 20, "output_tokens": 10}
    assert client.sent[1][-1]["role"] == "tool"


def test_bad_arguments_are_counted_as_invalid(registry):
    client = FakeClient()
    orig = client.create
    def broken(**kw):
        resp = orig(**kw)
        if len(client.sent) == 1:
            resp.choices[0].message.tool_calls[0].function.arguments = "{not json"
        return resp
    client.chat.completions.create = broken
    r = Agent(OpenAICompatModel("fake", "k", client=client), registry, "s", "u1").start("x")
    assert r.invalid_tool_calls == 1 and r.status == "ok"


def test_hidden_provider_fields_are_sent_back():
    """Gemini puts a thought signature on each tool call; it must come back unchanged."""
    from pydantic import BaseModel, ConfigDict

    class Fn(BaseModel):
        name: str
        arguments: str

    class TC(BaseModel):
        model_config = ConfigDict(extra="allow")
        id: str
        type: str
        function: Fn

    class Msg(BaseModel):
        model_config = ConfigDict(extra="allow")
        role: str = "assistant"
        content: str | None = None
        tool_calls: list[TC] | None = None

    sig = {"google": {"thought_signature": "SIG123"}}
    first = Msg(tool_calls=[TC(id="abc", type="function", extra_content=sig,
                               function=Fn(name="search_scholarships", arguments="{}"))])
    sent = []

    def create(model, messages, tools, temperature):
        sent.append(messages)
        if len(sent) == 1:
            return NS(choices=[NS(message=first)], usage=None)
        return NS(choices=[NS(message=Msg(content='{"answer": "ok", "sources": [], "caveats": []}'))], usage=None)

    client = NS(chat=NS(completions=NS(create=create)))
    model = OpenAICompatModel("gemini-test", "k", client=client)
    from agent.loop import Agent
    from agent.registry import ToolRegistry, Tool
    reg = ToolRegistry([Tool("search_scholarships", "find", {"type": "object", "properties": {}, "required": []},
                         lambda: {"count": 0})])
    r = Agent(model, reg, "s", "u1").start("hi")
    assert r.status == "ok", r.final
    back = sent[1][2]
    assert back["tool_calls"][0]["extra_content"] == sig
    assert sent[1][3]["tool_call_id"] == "abc"


def test_rate_limit_waits_and_retries(registry):
    class RateLimited(Exception):
        status_code = 429
    client = FakeClient()
    orig, calls = client.create, {"n": 0}
    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimited("Error code: 429 ... Please retry in 15.5s.")
        return orig(**kw)
    client.chat.completions.create = flaky
    waits = []
    model = OpenAICompatModel("fake", "k", client=client, sleep=waits.append)
    r = Agent(model, registry, "s", "u1").start("x")
    assert r.status == "ok" and waits == [16.5]


def test_other_errors_are_not_retried(registry):
    class BadRequest(Exception):
        status_code = 400
    client = FakeClient()
    def bad(**kw):
        raise BadRequest("Error code: 400")
    client.chat.completions.create = bad
    waits = []
    r = Agent(OpenAICompatModel("fake", "k", client=client, sleep=waits.append), registry, "s", "u1").start("x")
    assert r.status == "model_error" and waits == []


def test_model_list_follows_keys(monkeypatch):
    from agent import models
    monkeypatch.setattr(models, "_load_env", lambda: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    assert models.available_models() == ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
    m = models.make_model("qwen/qwen3.8-27b")
    assert m.name == "qwen/qwen3.8-27b" and "groq" in str(m.client.base_url)
    monkeypatch.delenv("GROQ_API_KEY")
    assert isinstance(models.model_from_env(), models.DemoModel)


def test_think_blocks_are_removed():
    reply = NS(choices=[NS(message=NS(tool_calls=None, content='<think>hmm</think>\n{"answer": "a"}'))], usage=None)
    client = NS(chat=NS(completions=NS(create=lambda **kw: reply)))
    out = OpenAICompatModel("q", "k", client=client).generate([{"role": "user", "content": "x"}], [])
    assert out.content == '{"answer": "a"}'


GROQ_400 = ('Error code: 400 - {"error":{"message":"Tool call validation failed: attempted to call tool \'JSON\' '
            'which was not in request.tools","type":"invalid_request_error","code":"tool_use_failed",'
            '"failed_generation":"{\\"name\\": \\"JSON\\", \\"arguments\\": {\\"answer\\":\\"Try DAAD.\\",'
            '\\"sources\\":[\\"https://daad.de\\"],\\"caveats\\":[]}}"}}')


def test_answer_wrapped_in_fake_tool_is_kept_and_counted(registry):
    class BadRequest(Exception):
        status_code = 400
    def create(**kw):
        raise BadRequest(GROQ_400)
    client = NS(chat=NS(completions=NS(create=create)))
    model = OpenAICompatModel("openai/gpt-oss-20b", "k", client=client)
    r = Agent(model, registry, "s", "u1").start("Which scholarships fit me?")
    assert r.status == "ok" and r.final["answer"] == "Try DAAD."
    assert r.invalid_tool_calls == 1 and model.rejected_tool_calls == 1
    assert any(s.kind == "invalid_tool_call" and s.name == "JSON" for s in r.steps)


def test_unrelated_400_still_fails(registry):
    class BadRequest(Exception):
        status_code = 400
    def create(**kw):
        raise BadRequest("Error code: 400 - bad request")
    client = NS(chat=NS(completions=NS(create=create)))
    r = Agent(OpenAICompatModel("m", "k", client=client), registry, "s", "u1").start("x")
    assert r.status == "model_error"


def test_long_rejected_answer_is_not_cut_off(registry):
    class BadRequest(Exception):
        status_code = 400
    long_answer = "A" * 3000
    err = GROQ_400.replace("Try DAAD.", long_answer)
    def create(**kw):
        raise BadRequest(err)
    client = NS(chat=NS(completions=NS(create=create)))
    r = Agent(OpenAICompatModel("m", "k", client=client), registry, "s", "u1").start("x")
    assert r.final["answer"] == long_answer
