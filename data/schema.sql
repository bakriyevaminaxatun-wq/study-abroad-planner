PRAGMA foreign_keys = ON;

-- Verified scholarship data. Re-created by data/load_sheet.py on every load.
CREATE TABLE IF NOT EXISTS scholarships (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  country TEXT NOT NULL,
  institution_or_funder TEXT,
  masters_status TEXT,
  funding_type TEXT,               -- full / partial / tuition_only / none (free text allowed)
  fields_of_study TEXT,            -- comma-separated, NULL = not stated
  min_gpa REAL,                    -- numeric part only, NULL = not stated or not a number
  min_gpa_text TEXT,               -- original text from the sheet
  language_requirements TEXT,
  min_language_score REAL,
  required_documents TEXT,
  application_fee REAL,
  fee_currency TEXT,
  fee_text TEXT,
  deadline_text TEXT,              -- free text exactly as written
  next_deadline_date TEXT,         -- ISO yyyy-mm-dd, only if one exact date exists
  source_url TEXT NOT NULL,
  last_verified TEXT NOT NULL,
  notes TEXT
);

-- application_id NULL = shared cost (e.g. IELTS), counted once.
CREATE TABLE IF NOT EXISTS cost_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id INTEGER REFERENCES scholarships(id),
  kind TEXT NOT NULL,
  label TEXT NOT NULL,
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  source_url TEXT,
  last_verified TEXT
);

-- Student data. NOT touched by the loader.
CREATE TABLE IF NOT EXISTS user_profiles (
  user_id TEXT PRIMARY KEY,
  field_of_study TEXT,
  gpa REAL,
  english_level TEXT,
  target_countries TEXT,
  savings_azn REAL DEFAULT 0,
  monthly_saving_azn REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chosen_applications (
  user_id TEXT REFERENCES user_profiles(user_id),
  scholarship_id INTEGER,
  status TEXT DEFAULT 'planned',
  PRIMARY KEY (user_id, scholarship_id)
);

CREATE TABLE IF NOT EXISTS completed_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT REFERENCES user_profiles(user_id),
  scholarship_id INTEGER,
  task TEXT NOT NULL,
  done_on TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT REFERENCES user_profiles(user_id),
  text TEXT NOT NULL,
  remind_on TEXT,
  approved INTEGER DEFAULT 0
);
