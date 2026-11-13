# Study Abroad Planner

An AI agent that helps Azerbaijani students plan a master's application abroad. It works in Azerbaijani and English.

## What it is for

Applying for scholarships abroad means tracking many deadlines, documents, fees and eligibility rules across different countries. Students often miss deadlines or underestimate the cost. This project gives the student one assistant that answers three questions:

1. **What should I do today?** A short plan based on the student's chosen applications and how much time they have.
2. **Which scholarships fit me?** Matching by field, GPA, English level, target country and funding type, with the closest deadline shown first.
3. **How much do I need to save?** The total cost in AZN for every chosen application, and how much to save per month to meet each deadline.

The agent also lists the documents still missing for a scholarship and explains where each fact comes from.

## What it will not do

- Submit applications, send emails or make payments.
- Predict or guarantee admission or scholarship chances.
- Write a motivation letter for the student to submit as their own.
- Invent a deadline, fee or scholarship. If a value is not in the database, it says so and points to the official page.

## How it works

The agent follows a loop until the task is done:

**receive request → load student profile → plan → call a tool → check the result → repeat → answer**

- **Approach:** ReAct, so the model decides the next step after each tool result.
- **Framework:** LangGraph (graph structure, human approval pauses, state between turns).
- **Step limit:** the loop stops after a fixed number of steps, and tool errors are returned to the model in readable form.
- **Human approval:** needed before saving a reminder or any export.
- **Answer format:** structured JSON, shown in a Streamlit chat with a side panel that displays every agent step and tool call.

## Tools

| Tool | What it does |
|---|---|
| `search_scholarships` | Filters the database by country, field, GPA, language score, deadline and funding type |
| `get_application_requirements` | Returns documents, fees, language requirements and the source link for one scholarship |
| `get_user_profile` / `update_user_profile` | Reads the student's profile and records progress and completed tasks |
| `get_deadlines` | Lists upcoming deadlines for the student's chosen applications, most urgent first |
| `calculate_budget` | Converts all costs to AZN and computes the total and the monthly saving needed |
| `search_guidance` | Searches advice on motivation letters, recommendation letters, CV, IELTS and document preparation |
| `add_reminder` | Saves a task or reminder after the student approves it |

All money math is done in code (`calculate_budget`), never by the language model. It handles currency conversion, a shared IELTS cost counted once, an optional retake buffer, and a check of whether each deadline is affordable.

## Data

The scholarship data lives in one Excel file, `study_abroad_data_sheet.xlsx`, with four tabs: **Instructions**, **Scholarships**, **Cost_Items** and **Rates**. It is loaded into SQLite for the agent.

- Every record has a **source URL** and a **last verified** date, and the agent shows both.
- Deadlines can be free text (for example "December or spring intake"). An optional exact date is used only for budget checks.
- If a round is closed or the next one is not announced, the agent says so instead of showing an old date.
- Guidance texts (tips, advice) are cleaned, saved as UTF-8 for Azerbaijani letters, split into chunks and stored in a vector database (ChromaDB) with a multilingual embedding model.

Starting scholarships include Chevening, DAAD, Erasmus Mundus, Stipendium Hungaricum, SISGP, Fulbright, Eiffel, the Netherlands NL Scholarship and the Azerbaijan State Program for studying abroad.

## Data collector agent

A second, smaller agent helps fill the Excel sheet. It searches the web, reads **official** scholarship pages and writes **draft** rows with an evidence note for each fact.

- It prefers official government, funder and university sites.
- It never guesses: anything missing is written as "not found".
- Drafts are marked "AI DRAFT - not verified". Only a human can verify a row and set its date.

## Safety and reliability

- Retrieved web text is treated as data, never as instructions (prompt-injection protection, tested).
- API keys are kept in a `.env` file that is excluded from GitHub.
- Tests use synthetic student profiles only. No real personal data is stored.

## Evaluation

The agent is tested with **24 tasks** (12 in Azerbaijani, 12 in English): simple one-tool tasks, multi-step tasks, and forbidden or unanswerable requests such as "guarantee I will win".

Three or more models are compared with the same prompt, tools and settings: at least one commercial model (Claude, GPT or Gemini) and two open-source models (for example Qwen and Llama or Mistral). For each model and language, the results report:

- task success rate
- tool selection and parameter accuracy
- average number of steps
- hallucinations and invented tool calls
- latency and cost per task

Every run is logged (steps, tool calls, duration, tokens, cost) in JSON files.

## Project structure

```
study-abroad-planner/
  agent/        registry.py (tools + schemas), loop.py (agent loop), models.py (model interface, fake model)
  app/          streamlit_app.py (chat, steps panel, profile form, approval buttons)
  data/         schema.sql, load_sheet.py (Excel -> database), guidance/ (advice notes), the Excel sheet
  tools/        budget.py, scholarships.py, profile.py, guidance.py, db.py
  prompts/      system_v1.md and CHANGELOG.md
  tests/        unit tests, test_set.json (24 agent tasks), build_test_set.py
  logs/         run logs (git-ignored)
```

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Then, one command per line:

```
python data/load_sheet.py          # Excel sheet -> database (only VERIFIED rows are loaded)
python -m tools.guidance           # build the guidance search database (downloads a small model the first time)
pytest                             # run all tests
streamlit run app/streamlit_app.py # open the interface (demo mode, no API key needed)
```

Add your API keys to `.env` later, when a real model is connected. Never commit that file.

## Status

| Part | State |
|---|---|
| Repository, database schema, Excel-to-database loader | Done, tested |
| `search_scholarships`, `get_application_requirements`, `get_deadlines`, profile tools, `add_reminder` | Done, tested |
| `calculate_budget` | Done, tested |
| Guidance knowledge base (cleaning, chunking, multilingual embeddings, search) | Done, tested with a fake embedder |
| Agent loop (step limit, retries, approval pause, injection-safe tool results) | Done, tested with a fake model |
| Streamlit interface layout | Done, runs in demo mode |
| 24-task test set (12 Azerbaijani, 12 English) | Written; runner for real models is planned |
| Scholarship data | Excel sheet has 3 AI drafts that need human verification |
| Data collector agent, real models, multi-model evaluation | Planned |

## Later ideas

More scholarships, a universities and programmes database, a Telegram bot or mobile app, daily "what to do today" notifications, and user accounts with document upload.
