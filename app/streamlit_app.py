"""Streamlit interface: chat, a side panel with every agent step, a profile form, approval buttons.

Run:  streamlit run app/streamlit_app.py
Uses a real model when GEMINI_API_KEY is set in .env, otherwise the scripted DemoModel.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

from agent.loop import Agent, load_system_prompt
from agent.models import MODELS, DemoModel, available_models, make_model, model_from_env
from agent.registry import build_default_registry
from tools.profile import get_user_profile, update_user_profile

USER_ID = "demo_user"
DB_PATH = os.environ.get("PLANNER_DB") or str(ROOT / "data" / "planner.sqlite")
RATES_PATH = os.environ.get("PLANNER_RATES") or str(ROOT / "data" / "rates.json")

TEXT = {
    "en": {"title": "Study Abroad Planner", "chat": "Ask about scholarships, deadlines or your budget...",
           "profile": "Your profile", "save": "Save profile", "steps": "Agent steps", "no_steps": "No steps yet.",
           "approve": "Approve", "deny": "Deny", "approval_q": "The assistant wants to save this reminder:",
           "demo": "Demo mode: a scripted stand-in is answering. Connect a real model to get real answers.",
           "no_db": "Database not found. Run: python data/load_sheet.py", "sources": "Sources",
           "caveats": "Please note", "field": "Field of study", "gpa": "GPA", "english": "English level",
           "countries": "Target countries", "savings": "Savings (AZN)", "monthly": "Monthly saving (AZN)",
           "saved": "Profile saved.", "language": "Language"},
    "az": {"title": "Xaricdə Təhsil Planlaşdırıcısı", "chat": "Təqaüdlər, son tarixlər və ya büdcə haqqında soruşun...",
           "profile": "Profiliniz", "save": "Profili saxla", "steps": "Agent addımları", "no_steps": "Hələ addım yoxdur.",
           "approve": "Təsdiq et", "deny": "Rədd et", "approval_q": "Köməkçi bu xatırlatmanı saxlamaq istəyir:",
           "demo": "Demo rejimi: real model yox, ssenari əsaslı əvəzedici cavab verir.",
           "no_db": "Verilənlər bazası tapılmadı. İşə salın: python data/load_sheet.py", "sources": "Mənbələr",
           "caveats": "Nəzərə alın", "field": "İxtisas sahəsi", "gpa": "GPA", "english": "İngilis dili səviyyəsi",
           "countries": "Hədəf ölkələr", "savings": "Yığım (AZN)", "monthly": "Aylıq qənaət (AZN)",
           "saved": "Profil saxlanıldı.", "language": "Dil"},
}


def get_model(model_id=None):
    return make_model(model_id) if model_id else model_from_env()


def get_agent(model_id=None):
    """One agent per chosen model. Choosing another model in the sidebar builds a new agent."""
    cur = st.session_state.get("agent")
    if cur is None or (model_id and getattr(cur.model, "name", None) != model_id):
        registry = build_default_registry(db_path=DB_PATH, rates_path=RATES_PATH)
        st.session_state.agent = Agent(get_model(model_id), registry, load_system_prompt(), USER_ID,
                                       approval_mode="ask", log_path=ROOT / "logs" / "app_runs.jsonl")
    return st.session_state.agent


def show_final(final, t):
    st.write(final["answer"])
    if final.get("sources"):
        st.caption(t["sources"] + ": " + " · ".join(final["sources"]))
    for c in final.get("caveats", []):
        st.warning(c)


def render_steps(result, t):
    if result is None or not result.steps:
        st.caption(t["no_steps"]); return
    for s in result.steps:
        label = {"tool_call": "🔧", "tool_result": "📥", "tool_error": "⚠️", "invalid_tool_call": "❌",
                 "approval": "✋", "final": "✅"}.get(s.kind, "•")
        with st.expander(f"{label} {s.n}. {s.kind} {s.name or ''}".strip(), expanded=False):
            if s.arguments:
                st.code(json.dumps(s.arguments, ensure_ascii=False, indent=2), language="json")
            if s.result is not None:
                st.code(json.dumps(s.result, ensure_ascii=False, indent=2, default=str)[:3000], language="json")


def main():
    st.set_page_config(page_title="Study Abroad Planner", layout="wide")
    lang = st.sidebar.radio("Language / Dil", ["en", "az"], horizontal=True,
                            format_func=lambda x: {"en": "English", "az": "Azərbaycanca"}[x])
    t = TEXT[lang]
    models = available_models()
    chosen = None
    if models:
        default = getattr(st.session_state.get("agent"), "model", None)
        default = getattr(default, "name", models[0])
        chosen = st.sidebar.selectbox(
            "Model", models, index=models.index(default) if default in models else 0,
            format_func=lambda m: f"{m} ({MODELS[m][1]})")
    get_agent(chosen)
    st.title(t["title"])
    if isinstance(get_agent().model, DemoModel):
        st.info(t["demo"])
    else:
        st.caption("Model: " + get_agent().model.name)
    if not Path(DB_PATH).exists():
        st.error(t["no_db"]); st.stop()

    # ---- sidebar: profile form ----
    with st.sidebar:
        st.subheader(t["profile"])
        try:
            cur = get_user_profile(USER_ID, db_path=DB_PATH)["profile"]
        except Exception:
            cur = {}
        with st.form("profile_form"):
            field = st.text_input(t["field"], cur.get("field_of_study") or "")
            gpa = st.number_input(t["gpa"], 0.0, 5.0, float(cur.get("gpa") or 0.0), 0.1)
            eng = st.text_input(t["english"], cur.get("english_level") or "")
            countries = st.text_input(t["countries"], cur.get("target_countries") or "")
            savings = st.number_input(t["savings"], 0.0, 1_000_000.0, float(cur.get("savings_azn") or 0.0), 50.0)
            monthly = st.number_input(t["monthly"], 0.0, 100_000.0, float(cur.get("monthly_saving_azn") or 0.0), 10.0)
            if st.form_submit_button(t["save"]):
                update_user_profile(USER_ID, {"field_of_study": field, "gpa": gpa, "english_level": eng,
                                              "target_countries": countries, "savings_azn": savings,
                                              "monthly_saving_azn": monthly}, db_path=DB_PATH)
                st.success(t["saved"])

    ss = st.session_state
    ss.setdefault("chat", [])        # [{"role","content"(text), "final"(dict)}]
    ss.setdefault("result", None)
    agent = get_agent()

    chat_col, steps_col = st.columns([2, 1])

    with chat_col:
        for m in ss.chat:
            with st.chat_message(m["role"]):
                if m.get("final"):
                    show_final(m["final"], t)
                else:
                    st.write(m["content"])

        result = ss.result
        if result is not None and result.status == "awaiting_approval":
            p = result.pending
            with st.chat_message("assistant"):
                st.write(t["approval_q"])
                st.code(json.dumps(p["arguments"], ensure_ascii=False, indent=2), language="json")
                c1, c2 = st.columns(2)
                decision = None
                if c1.button(t["approve"], key="approve"):
                    decision = True
                if c2.button(t["deny"], key="deny"):
                    decision = False
                if decision is not None:
                    ss.result = agent.resume(result, decision)
                    ss.chat.append({"role": "assistant", "content": ss.result.final["answer"], "final": ss.result.final})
                    st.rerun()

        prompt = st.chat_input(t["chat"], disabled=bool(result and result.status == "awaiting_approval"))
        if prompt:
            history = [{"role": m["role"], "content": m["content"]} for m in ss.chat]
            ss.chat.append({"role": "user", "content": prompt})
            ss.result = agent.start(prompt, history=history)
            if ss.result.status != "awaiting_approval":
                ss.chat.append({"role": "assistant", "content": ss.result.final["answer"], "final": ss.result.final})
            st.rerun()

    with steps_col:
        st.subheader(t["steps"])
        render_steps(ss.result, t)


main()
