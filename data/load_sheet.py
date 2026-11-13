"""Load study_abroad_data_sheet.xlsx into SQLite and rates.json.

Only VERIFIED rows are loaded: a row needs last_verified AND source_url, and
masters_status must not be 'excluded'. AI drafts that nobody checked stay out.
Student tables (profiles, reminders...) are never touched.

Usage:  python data/load_sheet.py [path/to/sheet.xlsx] [path/to/planner.sqlite]
"""
import json, re, sqlite3, sys
from datetime import date, datetime
from pathlib import Path
from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent


def to_text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*", str(v))
    return float(m.group(1).replace(",", ".")) if m else None


def to_date_text(v):
    """datetime/date -> ISO text; ISO-looking text -> ISO; other text kept as is."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    try:
        return date.fromisoformat(s[:10]).isoformat() if len(s) >= 10 else (s or None)
    except ValueError:
        return s or None


def iso_or_none(v):
    t = to_date_text(v)
    try:
        return date.fromisoformat(t).isoformat() if t else None
    except ValueError:
        return None


def read_sheet(ws):
    """Rows as dicts keyed by the first word of each header (lower case)."""
    headers = [str(c.value or "").split(" (")[0].strip().lower() for c in ws[1]]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if all(v in (None, "") for v in row):
            continue
        yield dict(zip(headers, row))


def load(xlsx_path, db_path=None, rates_path=None):
    xlsx_path = Path(xlsx_path)
    db_path = Path(db_path or HERE / "planner.sqlite")
    rates_path = Path(rates_path or HERE / "rates.json")
    wb = load_workbook(xlsx_path, data_only=True)
    report = {"loaded": [], "skipped": [], "cost_items": 0, "rates": 0}

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = OFF")
    con.executescript("DROP TABLE IF EXISTS cost_items; DROP TABLE IF EXISTS scholarships;")
    con.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys = ON")

    loaded_ids = set()
    for r in read_sheet(wb["Scholarships"]):
        sid, name = r.get("id"), to_text(r.get("name"))
        if sid in (None, "") or not name:
            continue
        sid = int(sid)
        status = (to_text(r.get("masters_status")) or "").lower()
        if status.startswith("exclude"):
            report["skipped"].append((sid, name, "excluded")); continue
        if not to_date_text(r.get("last_verified")):
            report["skipped"].append((sid, name, "not verified yet (last_verified empty)")); continue
        if not to_text(r.get("source_url")):
            report["skipped"].append((sid, name, "no source_url")); continue
        gpa_text = to_text(r.get("min_gpa"))
        fee_text = to_text(r.get("application_fee"))
        con.execute(
            """INSERT INTO scholarships (id,name,country,institution_or_funder,masters_status,
               funding_type,fields_of_study,min_gpa,min_gpa_text,language_requirements,
               min_language_score,required_documents,application_fee,fee_currency,fee_text,
               deadline_text,next_deadline_date,source_url,last_verified,notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, name, to_text(r.get("country")) or "", to_text(r.get("institution_or_funder")),
             status or None, (to_text(r.get("funding_type")) or "").lower() or None,
             to_text(r.get("fields_of_study")), to_num(r.get("min_gpa")), gpa_text,
             to_text(r.get("language_requirements")), to_num(r.get("min_language_score")),
             to_text(r.get("required_documents")), to_num(r.get("application_fee")),
             to_text(r.get("fee_currency")), fee_text,
             to_text(r.get("deadline")), iso_or_none(r.get("next_deadline_date")),
             to_text(r.get("source_url")), to_date_text(r.get("last_verified")), to_text(r.get("notes"))))
        loaded_ids.add(sid)
        report["loaded"].append((sid, name))

    for r in read_sheet(wb["Cost_Items"]):
        kind, amount, cur = to_text(r.get("kind")), to_num(r.get("amount")), to_text(r.get("currency"))
        if not kind or amount is None or not cur:
            continue
        app_id = r.get("scholarship_id")
        app_id = int(app_id) if app_id not in (None, "") else None
        if app_id is not None and app_id not in loaded_ids:
            report["skipped"].append((app_id, kind, "cost item of a scholarship that was not loaded")); continue
        con.execute("INSERT INTO cost_items (application_id,kind,label,amount,currency,source_url,last_verified)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (app_id, kind.lower(), to_text(r.get("label")) or kind, amount, cur.upper(),
                    to_text(r.get("source_url")), to_date_text(r.get("last_verified"))))
        report["cost_items"] += 1
    con.commit(); con.close()

    rates, dates, sources = {}, {}, {}
    if "Rates" in wb.sheetnames:
        for r in read_sheet(wb["Rates"]):
            cur, val = to_text(r.get("currency")), to_num(r.get("azn_per_1_unit"))
            if cur and val:
                rates[cur.upper()] = val
                dates[cur.upper()] = to_date_text(r.get("rate_date"))
                sources[cur.upper()] = to_text(r.get("source"))
    real_dates = [d for d in dates.values() if d]
    rates_path.write_text(json.dumps(
        {"date": min(real_dates) if real_dates else None, "rates": rates,
         "dates": dates, "sources": sources}, indent=2), encoding="utf-8")
    report["rates"] = len(rates)
    return report


if __name__ == "__main__":
    xlsx = sys.argv[1] if len(sys.argv) > 1 else HERE / "study_abroad_data_sheet.xlsx"
    rep = load(xlsx, sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"Loaded {len(rep['loaded'])} scholarships, {rep['cost_items']} cost items, {rep['rates']} rates.")
    for sid, name, why in rep["skipped"]:
        print(f"  skipped {sid} {name}: {why}")
