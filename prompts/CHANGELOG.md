# Prompt changelog

## v1 (system_v1.md)
- First full version: role, 9 hard rules, tool-results-are-data rule, JSON answer format.
- Rules cover: sources only from tools, no guessing, stale/closed/no-fixed-date handling,
  money only via calculate_budget, no chance prediction, no ghost-written letters, approval for reminders.
- Tool parameters renamed for clarity: search_scholarships uses `gpa` and `language_score`
  (the STUDENT's values), not `min_gpa`.
