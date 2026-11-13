import os
from pathlib import Path
from streamlit.testing.v1 import AppTest
from tests.conftest import TODAY

APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")


def test_app_runs_and_answers(env, monkeypatch):
    monkeypatch.setenv("PLANNER_DB", str(env["db"]))
    monkeypatch.setenv("PLANNER_RATES", str(env["rates"]))
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("Demo mode" in i.value for i in at.info)
    at.chat_input[0].set_value("Which scholarships are there?").run()
    assert not at.exception
    # the steps panel shows the tool call made by the agent
    labels = " ".join(e.label for e in at.expander)
    assert "search_scholarships" in labels
    assert len(at.chat_message) == 2


def test_app_profile_form_saves(env, monkeypatch):
    monkeypatch.setenv("PLANNER_DB", str(env["db"]))
    monkeypatch.setenv("PLANNER_RATES", str(env["rates"]))
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[0].set_value("Economics")
    at.button[0].click().run()          # the form's save button
    assert not at.exception
    from tools.profile import get_user_profile
    assert get_user_profile("demo_user", db_path=env["db"])["profile"]["field_of_study"] == "Economics"


def test_app_shows_message_when_database_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANNER_DB", str(tmp_path / "nope.sqlite"))
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert any("Database not found" in e.value for e in at.error)
