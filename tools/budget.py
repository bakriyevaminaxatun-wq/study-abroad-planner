"""calculate_budget: all money math happens here, in code, never in the model.

Rates are AZN per 1 unit of foreign currency. Missing rates raise an error
instead of guessing.
"""
from __future__ import annotations
import json, sqlite3
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from tools.db import DEFAULT_DB, DEFAULT_RATES, ToolError, connect

DAYS_PER_MONTH = Decimal("30.4375")
CENT = Decimal("0.01")


class MissingRateError(ValueError):
    pass


def _d(x) -> Decimal:
    return Decimal(str(x))


def _money(x: Decimal) -> float:
    return float(x.quantize(CENT, rounding=ROUND_HALF_UP))


def to_azn(amount, currency: str, rates: dict) -> Decimal:
    if currency == "AZN":
        return _d(amount)
    if currency not in rates:
        raise MissingRateError(f"No exchange rate for {currency}")
    return _d(amount) * _d(rates[currency])


def compute_budget(items, deadlines, rates, rate_date, current_savings_azn,
                   monthly_saving_azn, today, include_ielts=True,
                   include_retake_buffer=False):
    """Pure function. items: dicts with application_id (None = shared), kind,
    label, amount, currency. deadlines: {application_id: date or None}."""
    breakdown, total = [], Decimal(0)
    retake_done = False
    for it in items:
        if it["kind"] == "ielts" and not include_ielts:
            continue
        azn = to_azn(it["amount"], it["currency"], rates)
        rows = [(it["label"], azn, it)]
        if it["kind"] == "ielts" and include_retake_buffer and not retake_done:
            rows.append((it["label"] + " (retake buffer)", azn, it))
            retake_done = True
        for label, a, src in rows:
            total += a
            breakdown.append({
                "application_id": src.get("application_id"), "kind": src["kind"],
                "label": label, "original_amount": src["amount"],
                "currency": src["currency"], "amount_azn": _money(a)})

    savings, monthly = _d(current_savings_azn), _d(monthly_saving_azn)
    shared = sum((_d(b["amount_azn"]) for b in breakdown
                  if b["application_id"] is None), Decimal(0))
    app_ids = sorted({b["application_id"] for b in breakdown
                      if b["application_id"] is not None},
                     key=lambda i: (deadlines.get(i) is None, deadlines.get(i) or date.max, i))

    by_deadline, cumulative, first = [], Decimal(0), True
    for aid in app_ids:
        cumulative += sum((_d(b["amount_azn"]) for b in breakdown
                           if b["application_id"] == aid), Decimal(0))
        if first:           # shared costs (IELTS) are due before the earliest deadline
            cumulative += shared
            first = False
        dl = deadlines.get(aid)
        entry = {"application_id": aid, "deadline": dl.isoformat() if dl else None,
                 "cumulative_needed_azn": _money(cumulative)}
        if dl is None:
            entry["note"] = "no fixed deadline date in the database; cannot check affordability"
        elif dl < today:
            entry["note"] = "this deadline has already passed; affordability not checked"
        else:
            months = max(Decimal(0), _d((dl - today).days) / DAYS_PER_MONTH)
            available = savings + monthly * months
            shortfall = max(Decimal(0), cumulative - available)
            entry.update({
                "months_left": float(months.quantize(CENT)),
                "available_by_deadline_azn": _money(available),
                "shortfall_azn": _money(shortfall),
                "affordable": shortfall == 0,
                "required_monthly_saving_azn":
                    _money(max(Decimal(0), cumulative - savings) / months) if months > 0
                    else (0.0 if cumulative <= savings else None)})
        by_deadline.append(entry)

    return {"total_azn": _money(total), "breakdown": breakdown,
            "by_deadline": by_deadline, "exchange_rate_date": rate_date,
            "rates_used": {c: rates[c] for c in {b["currency"] for b in breakdown}
                           if c != "AZN"},
            "remaining_to_save_azn": _money(max(Decimal(0), total - savings))}


def calculate_budget(application_ids, current_savings_azn, monthly_saving_azn,
                     include_ielts=True, include_retake_buffer=False,
                     adhoc_items=None, db_path=None, rates_path=None, today=None):
    """Tool entry point: loads items from SQLite, rates from rates.json."""
    today = today or date.today()
    ids = [int(i) for i in (application_ids or [])]
    if not ids:
        raise ToolError("application_ids is empty. Choose at least one scholarship id first.")
    rates_file = Path(rates_path or DEFAULT_RATES)
    if not rates_file.exists():
        raise ToolError("Exchange rates file is missing. Fill the Rates tab and run load_sheet.py.")
    rj = json.loads(rates_file.read_text(encoding="utf-8"))
    con = connect(db_path)
    q = ",".join("?" * len(ids))
    found = {r["id"]: r["deadline_text"] for r in con.execute(
        f"SELECT id, deadline_text FROM scholarships WHERE id IN ({q})", ids)}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ToolError(f"Scholarship id(s) {missing} are not in the database.")
    rows = con.execute(
        f"SELECT application_id, kind, label, amount, currency FROM cost_items "
        f"WHERE application_id IN ({q}) OR application_id IS NULL", ids).fetchall()
    items = [dict(r) for r in rows] + list(adhoc_items or [])
    for it in items:
        it.setdefault("application_id", None)
        it.setdefault("kind", "other")
    deadlines = {r["id"]: parse_date(r["next_deadline_date"]) for r in con.execute(
        f"SELECT id, next_deadline_date FROM scholarships WHERE id IN ({q})", ids)}
    try:
        result = compute_budget(items, deadlines, rj["rates"], rj["date"],
                                current_savings_azn, monthly_saving_azn, today,
                                include_ielts, include_retake_buffer)
    except MissingRateError as e:
        raise ToolError(f"{e}. Add this currency to the Rates tab.") from e
    # scholarships with no cost items at all: say so instead of returning a silent 0
    with_costs = {r["application_id"] for r in rows if r["application_id"] is not None}
    result["applications_without_cost_items"] = [i for i in ids if i not in with_costs]
    no_date = [i for i in ids if deadlines.get(i) is None]
    result["applications_without_fixed_deadline"] = [
        {"application_id": i, "deadline_text": found[i]} for i in no_date]
    return result


def parse_date(v):
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


# JSON schema exposed to the model
TOOL_SCHEMA = {
    "name": "calculate_budget",
    "description": "Compute total cost in AZN for chosen applications, per-item breakdown, "
                   "exchange rate used, and whether the student can afford each deadline. "
                   "ALWAYS use this for money questions; never calculate yourself.",
    "parameters": {"type": "object", "properties": {
        "application_ids": {"type": "array", "items": {"type": "integer"}},
        "current_savings_azn": {"type": "number"},
        "monthly_saving_azn": {"type": "number"},
        "include_ielts": {"type": "boolean", "default": True},
        "include_retake_buffer": {"type": "boolean", "default": False},
        "adhoc_items": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "amount": {"type": "number"},
            "currency": {"type": "string"}, "kind": {"type": "string"}},
            "required": ["label", "amount", "currency"]}}},
        "required": ["application_ids", "current_savings_azn", "monthly_saving_azn"]}}
