"""Scholarship tools: search_scholarships, get_application_requirements, get_deadlines."""
from datetime import date, timedelta

from tools.db import (ToolError, connect, deadline_status, is_stale, parse_iso, today_or)

REQUIREMENT_FIELDS = {
    "deadline_text": "deadline", "application_fee": "application fee",
    "language_requirements": "language requirements", "required_documents": "required documents",
    "min_gpa_text": "minimum GPA", "funding_type": "funding type", "fields_of_study": "fields of study",
}


def _unknown_fields(row):
    return [label for col, label in REQUIREMENT_FIELDS.items() if row[col] in (None, "")]


def _card(row, today):
    status, days = deadline_status(row["next_deadline_date"], today)
    return {
        "id": row["id"], "name": row["name"], "country": row["country"],
        "institution_or_funder": row["institution_or_funder"],
        "funding_type": row["funding_type"],
        "deadline_text": row["deadline_text"],
        "next_deadline_date": row["next_deadline_date"],
        "deadline_status": status, "days_left": days,
        "source_url": row["source_url"], "last_verified": row["last_verified"],
        "stale_warning": is_stale(row["last_verified"], today),
        "not_stated_in_database": _unknown_fields(row),
    }


def _field_matches(wanted, fields_text):
    """Empty field text or 'All ...' / 'no restriction' means every subject is accepted."""
    if not fields_text:
        return True
    text = fields_text.lower().strip()
    if text.startswith(("all", "any")) or "no restriction" in text:
        return True
    return wanted.lower() in text


def search_scholarships(country=None, field=None, gpa=None, language_score=None,
                        deadline_before=None, funding_type=None,
                        db_path=None, today=None):
    """Filter verified scholarships. Unknown requirements never hide a scholarship;
    they are listed under not_stated_in_database."""
    today = today_or(today)
    limit = None
    if deadline_before:
        limit = parse_iso(deadline_before)
        if limit is None:
            raise ToolError("deadline_before must be a date like 2027-03-01.")
    con = connect(db_path)
    rows = con.execute("SELECT * FROM scholarships").fetchall()
    out = []
    for r in rows:
        if country and country.lower() not in (r["country"] or "").lower():
            continue
        if field and not _field_matches(field, r["fields_of_study"]):
            continue
        if gpa is not None and r["min_gpa"] is not None and r["min_gpa"] > float(gpa):
            continue
        if language_score is not None and r["min_language_score"] is not None \
                and r["min_language_score"] > float(language_score):
            continue
        if funding_type and (r["funding_type"] or "") != funding_type.lower():
            continue
        card = _card(r, today)
        if limit is not None:
            d = parse_iso(r["next_deadline_date"])
            if d is None or d < today or d > limit:
                continue
        out.append(card)
    order = {"upcoming": 0, "no_fixed_date": 1, "closed": 2}
    out.sort(key=lambda c: (order[c["deadline_status"]],
                            c["next_deadline_date"] or "9999", c["name"]))
    note = ("Only verified records are searched. 'closed' means the last known "
            "date has passed; 'no_fixed_date' means check deadline_text and the source page.")
    if not out:
        note = ("No scholarship matches ALL these filters. Do not repeat the same search: "
                "remove one filter (for example field or funding_type) and search again, "
                "or tell the student nothing matched. " + note)
    return {"count": len(out), "results": out, "note": note}


def get_application_requirements(scholarship_id, db_path=None, today=None):
    today = today_or(today)
    con = connect(db_path)
    try:
        sid = int(scholarship_id)
    except (TypeError, ValueError):
        raise ToolError("scholarship_id must be a whole number.")
    r = con.execute("SELECT * FROM scholarships WHERE id = ?", (sid,)).fetchone()
    if r is None:
        raise ToolError(f"Scholarship id {sid} is not in the database. "
                        "Use search_scholarships to find valid ids.")
    costs = [dict(c) for c in con.execute(
        "SELECT kind, label, amount, currency, source_url, last_verified FROM cost_items "
        "WHERE application_id = ? OR application_id IS NULL", (sid,))]
    card = _card(r, today)
    card.update({
        "masters_status": r["masters_status"],
        "fields_of_study": r["fields_of_study"],
        "min_gpa": r["min_gpa"], "min_gpa_text": r["min_gpa_text"],
        "language_requirements": r["language_requirements"],
        "min_language_score": r["min_language_score"],
        "required_documents": r["required_documents"],
        "application_fee": r["application_fee"], "fee_currency": r["fee_currency"],
        "fee_text": r["fee_text"], "notes": r["notes"],
        "cost_items": costs,
        "advice": ("Values listed in not_stated_in_database are missing: tell the student "
                   "and point to source_url. Never guess them."),
    })
    return card


def get_deadlines(user_id, days_ahead=90, db_path=None, today=None):
    today = today_or(today)
    try:
        days_ahead = int(days_ahead)
    except (TypeError, ValueError):
        raise ToolError("days_ahead must be a whole number of days.")
    con = connect(db_path)
    rows = con.execute(
        "SELECT s.* FROM chosen_applications c JOIN scholarships s ON s.id = c.scholarship_id "
        "WHERE c.user_id = ?", (user_id,)).fetchall()
    horizon = today + timedelta(days=days_ahead)
    upcoming, no_date, closed = [], [], []
    for r in rows:
        card = _card(r, today)
        if card["deadline_status"] == "upcoming":
            if parse_iso(r["next_deadline_date"]) <= horizon:
                upcoming.append(card)
        elif card["deadline_status"] == "no_fixed_date":
            no_date.append(card)
        else:
            closed.append(card)
    upcoming.sort(key=lambda c: c["next_deadline_date"])
    return {"chosen_applications": len(rows), "upcoming": upcoming,
            "no_fixed_date": no_date, "closed_or_past": closed,
            "note": "upcoming = exact date within days_ahead, most urgent first."}
