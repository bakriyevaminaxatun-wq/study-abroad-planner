"""Create an empty database (tables only). Use load_sheet.py to fill it."""
import sqlite3, pathlib
here = pathlib.Path(__file__).parent
db = here / "planner.sqlite"
with sqlite3.connect(db) as con:
    con.executescript((here / "schema.sql").read_text(encoding="utf-8"))
print(f"Created {db}")
