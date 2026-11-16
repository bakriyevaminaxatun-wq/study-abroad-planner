"""Model interface. Real models (Claude, GPT, Qwen...) implement the same `generate` method."""
from dataclasses import dataclass, field


@dataclass
class ModelReply:
    kind: str                       # "tool_call" or "final"
    name: str = None                # tool name (tool_call)
    arguments: dict = field(default_factory=dict)
    content: str = ""               # final answer text (usually JSON)
    usage: dict = field(default_factory=dict)   # {"input_tokens":..,"output_tokens":..}
    raw: dict = None                # the provider's own message, sent back unchanged (keeps hidden fields)


class ScriptedModel:
    """Fake model for tests: replays a fixed list of replies, in order."""
    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def generate(self, messages, tool_schemas):
        self.calls.append(len(messages))
        if not self.replies:
            raise RuntimeError("ScriptedModel has no replies left")
        return self.replies.pop(0)


def call(name, **arguments):
    return ModelReply("tool_call", name=name, arguments=arguments)


def final(answer, sources=(), caveats=()):
    import json
    return ModelReply("final", content=json.dumps(
        {"answer": answer, "sources": list(sources), "caveats": list(caveats)}, ensure_ascii=False))


class DemoModel:
    """Very simple rule-based stand-in so the Streamlit app runs without an API key."""
    name = "demo"

    def generate(self, messages, tool_schemas):
        last_tool = [m for m in messages if m["role"] == "tool"]
        user = [m for m in messages if m["role"] == "user"][-1]["content"].lower()
        if not last_tool:
            if any(w in user for w in ("deadline", "son tarix")):
                return call("get_deadlines", days_ahead=365)
            if any(w in user for w in ("profile", "profil")):
                return call("get_user_profile")
            return call("search_scholarships")
        return final("Demo mode (no real model connected): see the tool result in the steps panel.",
                     caveats=["This answer is scripted. Connect a real model to get real answers."])


class ModelAPIError(RuntimeError):
    """API error: short text for the screen, full text kept for parsing."""
    def __init__(self, full_text):
        super().__init__(full_text[:800].strip())
        self.full_text = full_text


class OpenAICompatModel:
    """A real model behind an OpenAI-compatible chat API (Gemini, OpenAI, Groq, Together...).

    One class for every provider, so all models get the same prompt, tools and settings.
    """

    RATE_LIMIT_RETRIES = 3      # free tiers allow only a few requests per minute
    MAX_WAIT_SECONDS = 65

    def __init__(self, model_name, api_key, base_url=None, temperature=0.0, client=None, sleep=None):
        import time
        self.name = model_name
        self.temperature = temperature
        self.sleep = sleep or time.sleep
        self.waited_seconds = 0.0
        self.rejected_tool_calls = 0   # provider refused a tool call (e.g. a made-up tool name); for the evaluation
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url)
        self.client = client

    @staticmethod
    def to_api_messages(messages):
        """Our loop's message list -> OpenAI chat format (tool calls need matching ids)."""
        import json
        out, last_id, n = [], None, 0
        for m in messages:
            if m["role"] == "assistant" and m.get("raw"):
                n += 1
                raw = dict(m["raw"])
                raw["role"] = "assistant"
                last_id = raw["tool_calls"][0].get("id") or f"call_{n}"
                raw["tool_calls"][0]["id"] = last_id
                out.append(raw)
            elif m["role"] == "assistant" and "tool_call" in m:
                n += 1
                last_id = f"call_{n}"
                tc = m["tool_call"]
                out.append({"role": "assistant", "content": None, "tool_calls": [{
                    "id": last_id, "type": "function",
                    "function": {"name": tc["name"] or "unknown",
                                 "arguments": json.dumps(tc["arguments"] or {}, ensure_ascii=False)}}]})
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": last_id or "call_0", "content": m["content"]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    def _create_with_retry(self, api_messages, tools):
        """Call the API. On a rate limit (HTTP 429) wait as long as the provider asks, then retry."""
        import re
        attempt = 0
        while True:
            try:
                return self.client.chat.completions.create(
                    model=self.name, messages=api_messages, tools=tools, temperature=self.temperature)
            except Exception as e:
                body = getattr(getattr(e, "response", None), "text", "") or ""
                text = f"{e} {body}"
                if getattr(e, "status_code", None) == 429 and attempt < self.RATE_LIMIT_RETRIES:
                    attempt += 1
                    m = re.search(r"retry in ([0-9.]+)s", text) or re.search(r'"retryDelay":\s*"([0-9.]+)s"', text)
                    wait = min(float(m.group(1)) + 1 if m else 20.0, self.MAX_WAIT_SECONDS)
                    self.waited_seconds += wait
                    self.sleep(wait)
                    continue
                raise ModelAPIError(text) from e

    @staticmethod
    def _failed_generation(err):
        """Groq rejects a call to a tool that does not exist (HTTP 400, code tool_use_failed) and
        returns what the model tried in 'failed_generation'. Returns that as a dict, or None."""
        import json
        import re
        text = getattr(err, "full_text", str(err))
        if "tool_use_failed" not in text:
            return None
        m = re.search(r'"failed_generation"\s*:\s*("(?:[^"\\]|\\.)*")', text)
        if not m:
            return None
        try:
            raw = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        try:                                   # format 1: {"name": "...", "arguments": {...}}
            gen = json.loads(raw)
            if isinstance(gen, dict):
                return gen
        except (json.JSONDecodeError, TypeError):
            pass
        f = re.search(r"<function=([\w\-.]+)>", raw)   # format 2: <tool_call><function=NAME>...</function>
        if f:
            args = dict(re.findall(r"<parameter=([\w\-.]+)>\s*(.*?)\s*</parameter>", raw, flags=re.S))
            return {"name": f.group(1), "arguments": args}
        return None

    def generate(self, messages, tool_schemas):
        import json
        tools = [{"type": "function", "function": s} for s in tool_schemas]
        try:
            resp = self._create_with_retry(self.to_api_messages(messages), tools)
        except ModelAPIError as e:
            gen = self._failed_generation(e)
            if gen is None:
                raise
            self.rejected_tool_calls += 1
            args = gen.get("arguments") if isinstance(gen.get("arguments"), dict) else {}
            if "answer" in args:            # the final answer was wrapped in a fake tool call: keep the answer
                return ModelReply("final", content=json.dumps(args, ensure_ascii=False),
                                  usage={"rejected_tool_call": gen.get("name")})
            # any other made-up tool: let the loop report "unknown tool" back to the model
            return ModelReply("tool_call", name=gen.get("name") or "unknown", arguments=args)
        msg = resp.choices[0].message
        usage = {}
        if getattr(resp, "usage", None):
            usage = {"input_tokens": resp.usage.prompt_tokens or 0,
                     "output_tokens": resp.usage.completion_tokens or 0}
        if msg.tool_calls:
            fn = msg.tool_calls[0].function
            try:
                args = json.loads(fn.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_unreadable_arguments": fn.arguments}   # the loop counts this as an invalid call
            raw = None
            if hasattr(msg, "model_dump"):        # keep every field the provider sent (e.g. Gemini thought signatures)
                dump = msg.model_dump(exclude_none=True)
                raw = {"role": "assistant", "tool_calls": dump["tool_calls"][:1]}   # one tool per step
                if "extra_content" in dump:
                    raw["extra_content"] = dump["extra_content"]
            return ModelReply("tool_call", name=fn.name, arguments=args, usage=usage, raw=raw)
        import re
        text = re.sub(r"<think>.*?</think>", "", msg.content or "", flags=re.S).strip()
        return ModelReply("final", content=text, usage=usage)


# ---- The models we compare. All use the same class, prompt, tools and settings. ----
PROVIDERS = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "key": "GEMINI_API_KEY"},
    "groq":   {"base_url": "https://api.groq.com/openai/v1",                          "key": "GROQ_API_KEY"},
}
MODELS = {   # model id -> (provider, type)
    "gemini-3.5-flash":   ("gemini", "commercial"),
    "openai/gpt-oss-20b": ("groq",   "open-source"),
    "qwen/qwen3.8-27b":   ("groq",   "open-source"),
}


def _load_env():
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass


def available_models():
    """Model ids whose API key is present in .env."""
    import os
    _load_env()
    return [m for m, (prov, _) in MODELS.items() if os.environ.get(PROVIDERS[prov]["key"], "").strip()]


def make_model(model_id):
    import os
    _load_env()
    prov = PROVIDERS[MODELS[model_id][0]]
    key = os.environ.get(prov["key"], "").strip()
    if not key:
        raise ValueError(f"{prov['key']} is missing in .env")
    return OpenAICompatModel(model_id, key, base_url=prov["base_url"])


def model_from_env():
    """Real model if an API key is in .env (MODEL_NAME picks which), otherwise the demo model."""
    import os
    avail = available_models()
    wanted = os.environ.get("MODEL_NAME", "").strip()
    if wanted in avail:
        return make_model(wanted)
    return make_model(avail[0]) if avail else DemoModel()
