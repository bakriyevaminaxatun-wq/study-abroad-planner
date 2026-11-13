"""Shared fixtures: a SYNTHETIC sheet (fake data) loaded into a temp database."""
import sys
from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

TODAY = date(2026, 11, 12)

SCHOL_HEADERS = ["id", "name", "country", "institution_or_funder", "masters_status", "what_to_check",
                 "source_url", "deadline (write anything)", "next_deadline_date (optional)", "min_gpa",
                 "language_requirements", "min_language_score", "application_fee", "fee_currency",
                 "required_documents", "funding_type", "fields_of_study", "last_verified", "notes"]


def make_sheet(path, poisoned_note=None):
    wb = Workbook()
    wb.active.title = "Instructions"
    ws = wb.create_sheet("Scholarships")
    ws.append(SCHOL_HEADERS)
    rows = [
        # id, name, country, funder, status, check, url, deadline_text, next_date, gpa, lang, lang_score, fee, cur, docs, funding, fields, verified, notes
        [1, "Test Scholarship Alpha", "Germany", "Alpha Fund", "include", None, "https://example.org/alpha",
         "15 Jan 2027", "2027-01-15", 3.0, "IELTS 6.5", 6.5, 50, "EUR", "CV; transcript; 2 letters",
         "full", "Computer Science, Engineering", "2026-10-01", None],
        [2, "Test Scholarship Beta", "UK", "Beta Trust", "include", None, "https://example.org/beta",
         "December or spring intake", None, "first class degree", "IELTS 7.0", 7.0, None, None, None,
         "partial", None, "2026-10-15", poisoned_note],
        [3, "Test Scholarship Gamma", "Hungary", "Gamma Gov", "include", None, "https://example.org/gamma",
         "5 Jun 2026 (closed)", "2026-06-05", 3.5, None, None, 0, "AZN", "Passport copy",
         "full", "All fields", "2026-09-01", None],
        [4, "Unverified Delta", "France", "Delta", "include", None, "https://example.org/delta",
         "1 Feb 2027", "2027-02-01", None, None, None, None, None, None, "full", None, None, None],
        [5, "Excluded Epsilon", "Turkey", "Epsilon", "excluded", None, "https://example.org/eps",
         "n/a", None, None, None, None, None, None, None, None, None, "2026-10-01", None],
        [6, "Old Zeta", "Sweden", "Zeta Institute", "include", None, "https://example.org/zeta",
         "1 Mar 2027", "2027-03-01", 3.2, "IELTS 6.5", 6.5, 20, "EUR", "CV", "full",
         "Computer Science", "2025-01-01", None],
    ]
    for r in rows:
        ws.append(r)
    ci = wb.create_sheet("Cost_Items")
    ci.append(["scholarship_id", "scholarship_name (auto)", "kind", "label", "amount", "currency",
               "source_url", "last_verified"])
    ci.append([None, "SHARED", "ielts", "IELTS exam", 200, "USD", "https://example.org/ielts", "2026-10-01"])
    ci.append([1, "x", "application_fee", "Alpha application fee", 50, "EUR", None, "2026-10-01"])
    ci.append([1, "x", "translation", "Diploma translation", 100, "AZN", None, "2026-10-01"])
    ci.append([4, "x", "application_fee", "Delta fee", 10, "EUR", None, None])   # parent not loaded
    ci.append([6, "x", "application_fee", "Zeta fee", 20, "EUR", None, "2026-10-01"])
    rt = wb.create_sheet("Rates")
    rt.append(["currency", "azn_per_1_unit", "rate_date", "source"])
    rt.append(["USD", 1.7, "2026-11-02", "synthetic"])      # fake rates for tests
    rt.append(["EUR", 2.0, "2026-11-02", "synthetic"])
    rt.append(["GBP", None, None, None])
    wb.save(path)


@pytest.fixture()
def env(tmp_path):
    """Returns dict(db, rates, xlsx) with the synthetic data loaded."""
    import load_sheet
    xlsx = tmp_path / "sheet.xlsx"
    make_sheet(xlsx)
    db, rates = tmp_path / "t.sqlite", tmp_path / "rates.json"
    report = load_sheet.load(xlsx, db, rates)
    return {"db": db, "rates": rates, "xlsx": xlsx, "report": report}


@pytest.fixture()
def student(env):
    from tools.profile import update_user_profile
    update_user_profile("u1", {"field_of_study": "Computer Science", "gpa": 3.4,
                               "english_level": "IELTS 7.0", "target_countries": "Germany, UK",
                               "savings_azn": 1500, "monthly_saving_azn": 300,
                               "add_chosen_application": 1}, db_path=env["db"], today=TODAY)
    update_user_profile("u1", {"add_chosen_application": 2}, db_path=env["db"])
    update_user_profile("u1", {"add_chosen_application": 3}, db_path=env["db"])
    return "u1"
