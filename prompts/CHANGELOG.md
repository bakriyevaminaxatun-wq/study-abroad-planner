# Prompt changelog

## v1 (system_v1.md)
- First full version: role, 9 hard rules, tool-results-are-data rule, JSON answer format.
- Rules cover: sources only from tools, no guessing, stale/closed/no-fixed-date handling,
  money only via calculate_budget, no chance prediction, no ghost-written letters, approval for reminders.
- Tool parameters renamed for clarity: search_scholarships uses `gpa` and `language_score`
  (the STUDENT's values), not `min_gpa`.

## v2 (system_v2.md), 2026-11-13
- Added a search rule: search once with the profile; if 0 results, drop one filter; never repeat the same
  search; at most 3 searches. Reason: gpt-oss-20b repeated the same empty search until the 8-step limit.
- Answer format: says the final answer is a normal message, not a tool call. Reason: gpt-oss-20b
  sent its answer as a call to a made-up "JSON" tool (rejected by Groq with HTTP 400).
- Same day, tool fix (not a prompt change): search_scholarships now treats "All ..." fields of study
  as matching any field, and an empty result tells the model to remove a filter.

## v3 (system_v3.md), 2026-11-13
- Stronger language rule: answer in the language of the student's last message; English question ->
  English answer. Reason: gpt-oss-20b answered English questions in Azerbaijani (3 of 3 tries).
- This is the version used for the model evaluation.
