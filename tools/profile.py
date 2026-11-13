"""Student profile tools: get_user_profile, update_user_profile, add_reminder."""

from tools.db import ToolError, connect, today_or

PROFILE_FIELDS = {"field_of_study": str, "gpa": float, "english_level": str,
                  "target_countries": str, "savings_azn": float, "monthly_saving_azn": float}


def get_user_profile(user_id, db_path=None):
    con = connect(db_path)
    p = con.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if p is None:
        raise ToolError("No profile found for this student yet. Ask the student for their "
                        "field, GPA, English level, target countries, savings and monthly saving, "
                        "then call update_user_profile.")
    apps = [dict(r) for r in con.execute(
        "SELECT c.scholarship_id, c.status, s.name FROM chosen_applications c "
        "LEFT JOIN scholarships s ON s.id = c.scholarship_id WHERE c.user_id = ?", (user_id,))]
    tasks = [dict(r) for r in con.execute(
        "SELECT scholarship_id, task, done_on FROM completed_tasks WHERE user_id = ? "
        "ORDER BY id", (user_id,))]
    return {"profile": dict(p), "chosen_applications": apps, "completed_tasks": tasks}


def update_user_profile(user_id, fields, db_path=None, today=None):
    """fields may contain profile values, add_chosen_application (id) and completed_task (text).
    All-or-nothing: if one field is invalid, nothing is saved."""
    if not isinstance(fields, dict) or not fields:
        raise ToolError("fields must be a non-empty object.")
    today = today_or(today)
    con = connect(db_path)
    try:
        con.execute("INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)", (user_id,))
        changed = []
        for key, value in fields.items():
            if key in PROFILE_FIELDS:
                try:
                    value = PROFILE_FIELDS[key](value)
                except (TypeError, ValueError):
                    raise ToolError(f"'{key}' has an invalid value: {value!r}.")
                con.execute(f"UPDATE user_profiles SET {key} = ? WHERE user_id = ?", (value, user_id))
            elif key == "add_chosen_application":
                try:
                    sid = int(value)
                except (TypeError, ValueError):
                    raise ToolError("add_chosen_application must be a scholarship id (whole number).")
                if con.execute("SELECT 1 FROM scholarships WHERE id = ?", (sid,)).fetchone() is None:
                    raise ToolError(f"Scholarship id {sid} is not in the database.")
                con.execute("INSERT OR IGNORE INTO chosen_applications (user_id, scholarship_id) "
                            "VALUES (?, ?)", (user_id, sid))
            elif key == "completed_task":
                con.execute("INSERT INTO completed_tasks (user_id, task, done_on) VALUES (?, ?, ?)",
                            (user_id, str(value), today.isoformat()))
            else:
                raise ToolError(f"Unknown field '{key}'. Allowed: {sorted(PROFILE_FIELDS)} plus "
                                "add_chosen_application and completed_task.")
            changed.append(key)
        con.commit()
        return {"updated": changed}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def add_reminder(user_id, text, date=None, db_path=None):
    """Saves a reminder. The agent loop asks the student for approval BEFORE calling this."""
    if not text or not str(text).strip():
        raise ToolError("Reminder text is empty.")
    con = connect(db_path)
    try:
        con.execute("INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)", (user_id,))
        cur = con.execute("INSERT INTO reminders (user_id, text, remind_on, approved) VALUES (?,?,?,1)",
                          (user_id, str(text).strip(), date))
        con.commit()
        return {"saved": True, "reminder_id": cur.lastrowid}
    finally:
        con.close()
