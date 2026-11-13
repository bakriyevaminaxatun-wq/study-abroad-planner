import pytest
from tests.conftest import TODAY
from tools.budget import calculate_budget
from tools.db import ToolError
from tools.profile import add_reminder, get_user_profile, update_user_profile
from tools.scholarships import get_application_requirements, get_deadlines, search_scholarships


def search(env, **kw):
    return search_scholarships(db_path=env["db"], today=TODAY, **kw)


# ---------- search_scholarships ----------
def test_search_all_sorted_upcoming_then_no_date_then_closed(env):
    r = search(env)
    assert [c["id"] for c in r["results"]] == [1, 6, 2, 3]
    assert [c["deadline_status"] for c in r["results"]] == ["upcoming", "upcoming", "no_fixed_date", "closed"]


def test_search_country_and_funding(env):
    assert [c["id"] for c in search(env, country="germany")["results"]] == [1]
    assert [c["id"] for c in search(env, funding_type="partial")["results"]] == [2]


def test_search_gpa_and_language_filters(env):
    # student GPA 3.1 hides Alpha? no (needs 3.0); hides Gamma (3.5)
    ids = [c["id"] for c in search(env, gpa=3.1)["results"]]
    assert 3 not in ids and 1 in ids
    # IELTS 6.0 hides everything that needs 6.5+ and keeps those with no stated score
    ids = [c["id"] for c in search(env, language_score=6.0)["results"]]
    assert ids == [3]


def test_unknown_requirements_do_not_hide_a_scholarship(env):
    ids = [c["id"] for c in search(env, gpa=2.0)["results"]]
    assert 2 in ids                      # min_gpa is text only, so it is unknown, not excluded


def test_search_field_filter_keeps_unknown_fields(env):
    ids = [c["id"] for c in search(env, field="Engineering")["results"]]
    assert 1 in ids and 2 in ids and 6 not in ids      # 2 has no fields stated -> kept


def test_deadline_before_only_exact_upcoming_dates(env):
    ids = [c["id"] for c in search(env, deadline_before="2027-02-01")["results"]]
    assert ids == [1]                    # no fixed-date and closed ones are excluded


def test_stale_and_unknown_flags(env):
    cards = {c["id"]: c for c in search(env)["results"]}
    assert cards[6]["stale_warning"] is True and cards[1]["stale_warning"] is False
    assert "application fee" in cards[2]["not_stated_in_database"]
    assert cards[1]["source_url"].startswith("https://")


def test_bad_deadline_input(env):
    with pytest.raises(ToolError):
        search(env, deadline_before="soon")


# ---------- get_application_requirements ----------
def test_requirements_include_costs_and_missing_fields(env):
    r = get_application_requirements(1, db_path=env["db"], today=TODAY)
    assert r["required_documents"].startswith("CV")
    labels = [c["label"] for c in r["cost_items"]]
    assert "Alpha application fee" in labels and "IELTS exam" in labels
    r2 = get_application_requirements(2, db_path=env["db"], today=TODAY)
    assert "required documents" in r2["not_stated_in_database"]
    assert r2["deadline_status"] == "no_fixed_date"


def test_requirements_unknown_id(env):
    with pytest.raises(ToolError) as e:
        get_application_requirements(4, db_path=env["db"], today=TODAY)   # unverified, not loaded
    assert "not in the database" in str(e.value)


# ---------- profile / deadlines ----------
def test_profile_roundtrip(env, student):
    p = get_user_profile(student, db_path=env["db"])
    assert p["profile"]["gpa"] == 3.4 and len(p["chosen_applications"]) == 3
    update_user_profile(student, {"completed_task": "Booked IELTS"}, db_path=env["db"], today=TODAY)
    assert get_user_profile(student, db_path=env["db"])["completed_tasks"][0]["task"] == "Booked IELTS"


def test_profile_errors(env, student):
    with pytest.raises(ToolError):
        get_user_profile("nobody", db_path=env["db"])
    with pytest.raises(ToolError):
        update_user_profile(student, {"hair_color": "x"}, db_path=env["db"])
    with pytest.raises(ToolError):
        update_user_profile(student, {"gpa": "abc"}, db_path=env["db"])
    with pytest.raises(ToolError):
        update_user_profile(student, {"add_chosen_application": 99}, db_path=env["db"])


def test_get_deadlines(env, student):
    r = get_deadlines(student, days_ahead=90, db_path=env["db"], today=TODAY)
    assert [c["id"] for c in r["upcoming"]] == [1]                 # 2027-01-15 is 64 days away
    assert [c["id"] for c in r["no_fixed_date"]] == [2]
    assert [c["id"] for c in r["closed_or_past"]] == [3]
    short = get_deadlines(student, days_ahead=10, db_path=env["db"], today=TODAY)
    assert short["upcoming"] == []


def test_add_reminder(env, student):
    r = add_reminder(student, "Book IELTS", "2026-12-01", db_path=env["db"])
    assert r["saved"] is True
    with pytest.raises(ToolError):
        add_reminder(student, "  ", db_path=env["db"])


# ---------- calculate_budget on the database ----------
def test_budget_from_database(env):
    r = calculate_budget([1], 0, 100, db_path=env["db"], rates_path=env["rates"], today=TODAY)
    # IELTS 200 USD*1.7=340 + fee 50 EUR*2=100 + translation 100 AZN = 540
    assert r["total_azn"] == 540.0
    assert r["exchange_rate_date"] == "2026-11-02"
    assert r["by_deadline"][0]["deadline"] == "2027-01-15"


def test_budget_flags_no_fixed_date_and_closed(env):
    r = calculate_budget([1, 2, 3, 6], 0, 0, db_path=env["db"], rates_path=env["rates"], today=TODAY)
    assert r["applications_without_fixed_deadline"][0]["deadline_text"] == "December or spring intake"
    assert 2 in r["applications_without_cost_items"] and 3 in r["applications_without_cost_items"]


def test_budget_errors(env):
    with pytest.raises(ToolError):
        calculate_budget([], 0, 0, db_path=env["db"], rates_path=env["rates"])
    with pytest.raises(ToolError):
        calculate_budget([99], 0, 0, db_path=env["db"], rates_path=env["rates"])
    with pytest.raises(ToolError) as e:
        calculate_budget([1], 0, 0, adhoc_items=[{"label": "x", "amount": 5, "currency": "GBP"}],
                         db_path=env["db"], rates_path=env["rates"])
    assert "GBP" in str(e.value)
