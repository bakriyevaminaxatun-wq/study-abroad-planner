"""Shared database helpers and tool error types."""
import sqlite3
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "planner.sqlite"
DEFAULT_RATES = ROOT / "data" / "rates.json"
STALE_AFTER_DAYS = 180   # records older than this get a warning


class ToolError(Exception):
    """A readable error returned to the model (bad id, bad input, ...)."""


class TransientToolError(ToolError):
    """A temporary failure; the agent loop may retry."""


def connect(db_path=None):
    con = sqlite3.connect(db_path or DEFAULT_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def parse_iso(value):
    """Return a date for an ISO string, else None."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def today_or(today):
    return today or date.today()


def deadline_status(next_deadline_date, today):
    """upcoming / closed / no_fixed_date, plus days_left."""
    d = parse_iso(next_deadline_date)
    if d is None:
        return "no_fixed_date", None
    days = (d - today).days
    return ("upcoming" if days >= 0 else "closed"), days


def is_stale(last_verified, today, limit=STALE_AFTER_DAYS):
    d = parse_iso(last_verified)
    return d is None or (today - d).days > limit
