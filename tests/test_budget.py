"""Hand-computed cases. All numbers are SYNTHETIC test values, not real fees/rates."""
from datetime import date
import pytest
from tools.budget import compute_budget, MissingRateError

RATES = {"USD": 2.0, "EUR": 3.0}   # synthetic
TODAY = date(2026, 11, 3)

def item(aid, kind, amount, cur, label=None):
    return {"application_id": aid, "kind": kind, "amount": amount,
            "currency": cur, "label": label or kind}

def run(items, deadlines, savings=0, monthly=0, **kw):
    return compute_budget(items, deadlines, RATES, "2026-11-01", savings, monthly, TODAY, **kw)

def test_conversion_and_total():
    r = run([item(1, "application_fee", 50, "USD"), item(1, "translation", 100, "AZN")],
            {1: date(2027, 1, 1)})
    assert r["total_azn"] == 200.0          # 50*2 + 100
    assert r["breakdown"][0]["amount_azn"] == 100.0

def test_missing_rate_raises():
    with pytest.raises(MissingRateError):
        run([item(1, "application_fee", 10, "GBP")], {1: date(2027, 1, 1)})

def test_ielts_toggle_and_retake():
    items = [item(None, "ielts", 100, "USD"), item(1, "application_fee", 10, "EUR")]
    d = {1: date(2027, 1, 1)}
    assert run(items, d)["total_azn"] == 230.0
    assert run(items, d, include_ielts=False)["total_azn"] == 30.0
    assert run(items, d, include_retake_buffer=True)["total_azn"] == 430.0

def test_shared_cost_counted_once():
    items = [item(None, "ielts", 100, "AZN"), item(1, "application_fee", 10, "AZN"),
             item(2, "application_fee", 10, "AZN")]
    r = run(items, {1: date(2027, 1, 1), 2: date(2027, 2, 1)})
    assert r["total_azn"] == 120.0
    assert [e["cumulative_needed_azn"] for e in r["by_deadline"]] == [110.0, 120.0]

def test_deadline_order_and_affordability():
    items = [item(1, "application_fee", 300, "AZN"), item(2, "application_fee", 100, "AZN")]
    # app 2 deadline is earlier -> first
    d = {1: date(2027, 3, 1), 2: date(2026, 12, 3)}   # 30 days -> 0.9856 months
    r = run(items, d, savings=50, monthly=0)
    assert [e["application_id"] for e in r["by_deadline"]] == [2, 1]
    assert r["by_deadline"][0]["shortfall_azn"] == 50.0
    assert r["by_deadline"][0]["affordable"] is False

def test_required_monthly_saving():
    # deadline 2027-01-02 = 60 days = 60/30.4375 months
    r = run([item(1, "application_fee", 1000, "AZN")], {1: date(2027, 1, 2)}, savings=200)
    months = 60 / 30.4375
    assert r["by_deadline"][0]["required_monthly_saving_azn"] == round(800 / months, 2)

def test_affordable_with_monthly_saving():
    r = run([item(1, "application_fee", 100, "AZN")], {1: date(2027, 11, 3)},
            savings=0, monthly=50)
    assert r["by_deadline"][0]["affordable"] is True

def test_missing_deadline_flagged():
    r = run([item(1, "application_fee", 10, "AZN")], {1: None})
    assert "note" in r["by_deadline"][0]
