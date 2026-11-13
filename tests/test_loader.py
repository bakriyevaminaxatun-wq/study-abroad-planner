import json
from tools.db import connect


def test_only_verified_rows_are_loaded(env):
    ids = {i for i, _ in env["report"]["loaded"]}
    assert ids == {1, 2, 3, 6}                      # 4 unverified, 5 excluded
    reasons = [(sid, why) for sid, _, why in env["report"]["skipped"]]
    assert (4, "not verified yet (last_verified empty)") in reasons
    assert (5, "excluded") in reasons


def test_free_text_and_numbers(env):
    con = connect(env["db"])
    b = con.execute("SELECT * FROM scholarships WHERE id = 2").fetchone()
    assert b["deadline_text"] == "December or spring intake"
    assert b["next_deadline_date"] is None
    assert b["min_gpa"] is None and b["min_gpa_text"] == "first class degree"
    a = con.execute("SELECT * FROM scholarships WHERE id = 1").fetchone()
    assert a["next_deadline_date"] == "2027-01-15" and a["min_gpa"] == 3.0
    assert a["application_fee"] == 50.0 and a["fee_currency"] == "EUR"


def test_cost_items_skip_unloaded_parent(env):
    con = connect(env["db"])
    kinds = [r["label"] for r in con.execute("SELECT label FROM cost_items")]
    assert "Delta fee" not in kinds
    assert "IELTS exam" in kinds
    assert env["report"]["cost_items"] == 4


def test_rates_file(env):
    rj = json.loads(env["rates"].read_text())
    assert rj["rates"] == {"USD": 1.7, "EUR": 2.0}   # GBP empty -> not written
    assert rj["date"] == "2026-11-02"


def test_reload_keeps_student_data(env, student):
    import load_sheet
    load_sheet.load(env["xlsx"], env["db"], env["rates"])
    con = connect(env["db"])
    assert con.execute("SELECT COUNT(*) FROM user_profiles").fetchone()[0] == 1
