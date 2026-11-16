# Model evaluation results

Tasks: 24 per model (12 Azerbaijani, 12 English). Prompt: system_v3. A task succeeds only if all its checks pass.
Cost: all runs used free tiers (real cost 0). `cost_per_task_usd` is what the same tokens would cost on the paid tier (prices in eval/prices.json). `avg_seconds` includes waiting for free-tier rate limits; the next column leaves that waiting out.

## Azerbaijani tasks

| model | type | tasks | success_rate_% | tool_selection_% | valid_tool_calls_% | avg_model_calls | tasks_with_hallucination | invented_or_invalid_tool_calls | errors_or_step_limit | avg_seconds | avg_seconds_without_rate_limit_wait | avg_input_tokens | avg_output_tokens | cost_per_task_usd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash | commercial | 4 | 100.0 | 100.0 | 100.0 | 3.25 | 0 | 0 | 0 | 32.88 | 10.89 | 6970 | 343 | 0.01354 |
| openai/gpt-oss-20b | open-source | 12 | 41.7 | 75.0 | 54.5 | 4.42 | 3 | 20 | 3 | 34.23 | 34.23 | 7277 | 868 | 0.00081 |
| qwen/qwen3.8-27b | open-source | 8 | 62.5 | 87.5 | 100.0 | 2.88 | 2 | 0 | 1 | 46.7 | 31.7 | 6246 | 406 | 0.00662 |

## English tasks

| model | type | tasks | success_rate_% | tool_selection_% | valid_tool_calls_% | avg_model_calls | tasks_with_hallucination | invented_or_invalid_tool_calls | errors_or_step_limit | avg_seconds | avg_seconds_without_rate_limit_wait | avg_input_tokens | avg_output_tokens | cost_per_task_usd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash | commercial | 1 | 0.0 | 100.0 | 100.0 | 3.0 | 0 | 0 | 1 | 172.72 | 14.99 | 5726 | 48 | 0.00902 |
| openai/gpt-oss-20b | open-source | 12 | 33.3 | 75.0 | 72.4 | 3.33 | 1 | 8 | 1 | 37.02 | 35.35 | 5078 | 805 | 0.00062 |
| qwen/qwen3.8-27b | open-source | 4 | 50.0 | 100.0 | 100.0 | 2.25 | 0 | 0 | 0 | 47.65 | 47.65 | 4694 | 203 | 0.00457 |

## All tasks

| model | type | tasks | success_rate_% | tool_selection_% | valid_tool_calls_% | avg_model_calls | tasks_with_hallucination | invented_or_invalid_tool_calls | errors_or_step_limit | avg_seconds | avg_seconds_without_rate_limit_wait | avg_input_tokens | avg_output_tokens | cost_per_task_usd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash | commercial | 5 | 80.0 | 100.0 | 100.0 | 3.2 | 0 | 0 | 1 | 60.85 | 11.71 | 6721 | 284 | 0.01264 |
| openai/gpt-oss-20b | open-source | 24 | 37.5 | 75.0 | 61.6 | 3.88 | 4 | 28 | 4 | 35.62 | 34.79 | 6177 | 837 | 0.00071 |
| qwen/qwen3.8-27b | open-source | 12 | 58.3 | 91.7 | 100.0 | 2.67 | 2 | 0 | 1 | 47.02 | 37.02 | 5728 | 338 | 0.00594 |

## Success by task type

| model | simple | multi | forbidden |
|---|---|---|---|
| gemini-3.5-flash | 4/5 | 0/0 | 0/0 |
| openai/gpt-oss-20b | 7/8 | 1/10 | 1/6 |
| qwen/qwen3.8-27b | 5/8 | 2/4 | 0/0 |

## Pass rate of each check

`keyword` checks look for typical words and can be wrong: read those answers in scored_tasks.csv.

| check | method | gemini-3.5-flash | openai/gpt-oss-20b | qwen/qwen3.8-27b |
|---|---|---|---|---|
| answer_language_matches | exact | 5/5 | 18/24 | 11/12 |
| asks_approval_before_save | exact | 0/0 | 1/2 | 0/0 |
| budget_matches_calculator | exact | 0/0 | 2/6 | 0/2 |
| closed_or_no_date_stated | keyword | 1/1 | 4/7 | 4/4 |
| every_deadline_has_source | exact | 3/3 | 11/11 | 7/7 |
| final_json_format | exact | 4/5 | 20/24 | 8/12 |
| ignores_injected_instruction | exact | 0/0 | 2/2 | 0/0 |
| no_invented_deadline | exact | 1/1 | 5/5 | 3/3 |
| no_scholarship_outside_database | exact | 2/2 | 4/4 | 3/3 |
| no_tool_called:add_reminder | exact | 0/0 | 1/1 | 0/0 |
| offers_allowed_help | keyword | 0/0 | 3/3 | 0/0 |
| refuses_ghostwriting | keyword | 0/0 | 0/1 | 0/0 |
| refuses_guarantee_or_prediction | keyword | 0/0 | 0/2 | 0/0 |
| says_missing_values | keyword | 0/0 | 2/3 | 1/1 |
| tools_called_in_order | exact | 5/5 | 18/24 | 11/12 |
| uses_profile_values | keyword | 1/1 | 7/10 | 6/6 |
