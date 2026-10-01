<div align="center">

# 🛡️ DB Copilot

**Talk to your relational database in plain language — safely.**

A RAG + SQL-agent copilot that documents, queries and (with human approval) modifies a live
PostgreSQL database, built on LangGraph with AST-based SQL guardrails and a persistent
Human-in-the-Loop approval flow.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-ReAct%20agent-1C3C3C)
![Streamlit](https://img.shields.io/badge/Streamlit-UI-FF4B4B?logo=streamlit&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-demo%20DB-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/tests-52%20passing-2EA44F)

</div>

---

## Overview

In most organizations, understanding a relational data model and writing correct SQL depends on a
handful of people — the engineers or DBAs who know the database by heart. Everyone else (analysts,
business teams, new hires) has to queue up behind them.

**DB Copilot** removes that bottleneck with two complementary modes:

| Mode | What it answers | Touches data? |
|---|---|---|
| **Documentation mode (RAG)** | "What tables are there?", "How does `orders` relate to `customers`?", "What does `status` mean?" | No — works only on schema metadata |
| **Agent mode (SQL)** | "How many orders were placed last month?", "Who is our top customer?", "Mark order 42 as shipped" | Yes — reads run directly, **every write requires human approval** |

The system is database- and provider-agnostic: point `DATABASE_URL` at any PostgreSQL database and
choose Gemini or OpenAI through environment variables.

> Built as the final project (TP2) for the *Intelligent Systems* course at Universidad Tecnológica
> Nacional (UTN), Argentina.

---

## Key features

- 🤖 **A real agent, not a fixed pipeline.** A LangGraph ReAct agent decides at every step which tool to
  call: `list_tables`, `describe_table`, `retrieve_schema`, `run_select` or `run_write`.
- 🔁 **Self-correcting SQL.** When a query fails, the database error is returned to the agent as text; it
  reads it, fixes the SQL and retries on its own.
- 🧱 **AST-based guardrails.** Every statement is parsed with `sqlglot` and classified before it runs —
  no regex that can be bypassed with comments or string tricks.
- ✋ **Human-in-the-Loop.** `INSERT` / `UPDATE` / `DELETE` are never executed directly: they are queued
  and only run after an operator explicitly approves them in the UI.
- 📜 **Persistent audit log.** Approval queue and audit trail live in SQLite, survive restarts and are
  scoped per session.
- 🔍 **Live schema introspection.** The schema is always read from the database itself, and
  `COMMENT ON TABLE` / `COMMENT ON COLUMN` are used as business context for RAG — no hand-maintained
  synonym dictionaries.
- 🗺️ **Auto-generated ER diagram** (DBML → SVG) and reconstructed DDL for every table.
- 🐳 **One-command demo database.** A reproducible e-commerce dataset (Faker, fixed seed) ships with
  Docker Compose, so anyone can try the project without their own data or credentials.

---

## Architecture

<p align="center">
  <img src="assets/architecture.png" alt="DB Copilot architecture: Streamlit UI routes questions to a RAG documentation mode or a LangGraph ReAct agent whose SQL passes through a sqlglot guardrail — reads run, writes go to human approval, DDL is blocked" width="100%">
</p>

<details>
<summary>Text version (Mermaid)</summary>

```mermaid
flowchart TD
    U([User — natural language]) --> UI[Streamlit UI<br/>Chat · Schema · Diagram · Audit]
    UI --> M{Mode}

    M -->|Documentation| RAG[Semantic retriever<br/>Chroma over live schema docs]
    RAG --> LLM1[LLM synthesis]

    M -->|Agent| AG[LangGraph ReAct agent]
    AG --> T[Tools: list_tables · describe_table ·<br/>retrieve_schema · run_select · run_write]
    T --> G{SQL guardrail<br/>sqlglot AST}

    G -->|SELECT| R[Execute with auto-injected LIMIT]
    R --> DF[Full DataFrame → UI<br/>short summary → LLM]
    G -->|INSERT / UPDATE / DELETE| Q[Approval queue - HITL]
    Q -->|Approved| X[Execute]
    Q -->|Rejected| C[Cancel]
    G -->|DROP / ALTER / CREATE / TRUNCATE| B[Blocked]

    X --> A[(Audit log · SQLite)]
    C --> A
    DB[(PostgreSQL)] -. live introspection .-> RAG
    DB -. live introspection .-> AG
```

</details>

### Data channel vs. conversational channel

`run_select` stores the **full** result as a `DataFrame` for the UI, while the LLM only receives a
compact summary (row count, columns and a two-row sample). This keeps thousands of rows out of the
prompt — cutting cost and latency, and removing the risk of the model "transcribing" (and
hallucinating) data.

### SQL guardrail classification

| Category | Examples | Behavior |
|---|---|---|
| **Read** | `SELECT`, `WITH`, `UNION`, `INTERSECT`, `EXCEPT` | Executed immediately; a `LIMIT` (default 500) is injected if missing |
| **Write** | `INSERT`, `UPDATE`, `DELETE` | Queued for human approval |
| **Forbidden** | `DROP`, `ALTER`, `CREATE`, `TRUNCATE` | Always blocked |
| **Invalid** | Unparseable SQL or multiple statements | Rejected; the agent is asked to fix it |

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Agent orchestration | LangGraph (`create_react_agent`) + LangChain |
| LLM & embeddings | Google Gemini or OpenAI (configurable) |
| Vector store | Chroma |
| SQL parsing / guardrails | sqlglot |
| Database access | SQLAlchemy + psycopg2 (PostgreSQL) |
| Audit & approval queue | SQLite |
| UI | Streamlit (custom CSS theme) |
| ER diagrams | DBML + `@softwaretechnik/dbml-renderer` (Node.js) |
| Demo database | Docker Compose + Faker |
| Testing | pytest |

---

## Getting started

### Prerequisites

- Python 3.10+
- An API key for **Google Gemini** or **OpenAI**
- *Optional:* Docker (for the demo database) and Node.js (for the SVG ER diagram)

### Quick start (Windows)

Double-click [`start_app.bat`](start_app.bat). It creates a virtual environment, installs dependencies,
creates `.env` from the template (and opens it so you can add your API key), starts the demo database
with Docker if available, installs the Node dependency for the diagram, and launches the app at
`http://localhost:8501`.

### Manual setup (Linux / macOS / Windows)

```bash
# 1. Clone and install
git clone https://github.com/Lumansito/tp2-ia-utn.git
cd tp2-ia-utn
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
npm install                                          # optional, for the ER diagram

# 2. Configure
cp .env.example .env                                 # then edit .env

# 3. Start the demo database (skip if you use your own)
docker compose up -d
python scripts/verify_demo_db.py                     # checks the seed data loaded correctly

# 4. Run
streamlit run db_copilot/app.py
```

### Configuration

| Variable | Description | Example |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy connection string of the target database | `postgresql+psycopg2://postgres:postgres@localhost:5432/ecommerce_db` |
| `LLM_PROVIDER` | `GEMINI` or `OPENAI` | `GEMINI` |
| `LLM_API_KEY` | API key for the selected provider | — |
| `LLM_MODEL` | Chat model name | `gemini-3.8-flash` / `gpt-4o-mini` |
| `EMBEDDING_MODEL` | Embedding model name | `models/gemini-embedding-001` / `text-embedding-3-small` |
| `POSTGRES_PORT` | Host port for the demo database container | `5432` |

If any required variable is missing, the app **refuses to start** with a clear error. This is
intentional: there is no silent fallback to a degraded mode.

> **Tip:** provider model names change over time. If you get a `NOT_FOUND` / "model no longer
> available" error, check the provider's docs and update `LLM_MODEL`.

### Demo database

`docker-compose.yml` starts PostgreSQL pre-loaded with an e-commerce schema — categories, products,
customers, orders, order items and payments — generated deterministically with Faker (`SEED=42`) and
documented with `COMMENT ON` statements so the RAG mode has business context to work with. If port
`5432` is already in use, set `POSTGRES_PORT` (and the port in `DATABASE_URL`) in your `.env`.

---

## Usage

Once the app is running you can:

- **Chat** in *Documentation* or *Agent* mode and see a step-by-step timeline of every tool call.
- **Browse the schema** — columns, keys, indexes and reconstructed DDL for each table.
- **View the ER diagram**, generated automatically from the live schema.
- **Approve or reject** writes proposed by the agent from the Human-in-the-Loop panel.
- **Inspect the audit log** of every read, write proposal, approval and rejection.

Example prompts:

```text
Documentation:  What is the relationship between orders and payments?
Agent:          Which 5 customers spent the most in 2025?
Agent (write):  Change the status of order 17 to 'shipped'   → goes to the approval queue
```

---

## Testing

```bash
pytest
```

52 tests cover the SQL guardrails, configuration validation, schema introspection (including DBML
generation) and the agent tools end-to-end — including the full approval flow — using in-memory
SQLite. The suite needs **no network access and no API keys**. Behavior against a real LLM is
validated manually through the app.

---

## Project structure

```
tp2-ia-utn/
├── db_copilot/
│   ├── config.py                # .env loading, SQLAlchemy engine, LLM & embedding factories
│   ├── schema_introspection.py  # Live catalog introspection, RAG documents, DBML / DDL generation
│   ├── rag.py                   # Chroma vector store
│   ├── sql_guard.py             # sqlglot-based guardrails (classification, LIMIT injection, DDL blocking)
│   ├── agent.py                 # Agent tools, LangGraph ReAct agent, HITL approval
│   ├── audit_store.py           # SQLite-backed audit log and approval queue
│   └── app.py                   # Streamlit app (Chat, Schema, ER Diagram, Audit)
├── scripts/
│   ├── generate_demo_sql.py     # Generates the demo database SQL (Faker, fixed seed)
│   └── verify_demo_db.py        # Verifies the Docker demo database loaded correctly
├── docker/init/                 # SQL executed by Postgres on first start
├── tests/                       # pytest suite
├── render_dbml.js               # DBML → SVG renderer (Node.js)
├── docker-compose.yml
├── start_app.bat                # One-click setup & launch on Windows
├── requirements.txt
└── .env.example
```

> The user interface and code comments are in Spanish, as the project was developed for a
> Spanish-speaking university course.

---

## Design decisions & lessons learned

Some of the more interesting problems we ran into while building it:

| Challenge | Resolution |
|---|---|
| The guardrail wrongly blocked legitimate reads using `UNION` / `INTERSECT` / `EXCEPT` | Added those AST node types to the read classification |
| The approval queue and audit log were in-memory dicts — lost on restart and shared across users | Persisted them in SQLite, scoped by session (`thread_id`) |
| Embeddings silently fell back to a local, non-semantic `HashingVectorizer` | Removed the fallback: real embeddings or the app does not start |
| Types such as `NUMERIC(10, 2)` broke the DBML parser and the ER diagram | Quote any column type containing spaces before emitting DBML |
| Schema context depended on a hand-written synonym dictionary tied to one data model | Read `COMMENT ON` metadata from the database itself, making the system work with any schema |
| Row counts for large tables were slow (`COUNT(*)`) | Use PostgreSQL's `pg_class.reltuples` estimate |

---

## Authors

| Name | GitHub | LinkedIn |
|---|---|---|
| Santino Cataldi | [@SrNanu](https://github.com/SrNanu) | [santino-cataldi](https://www.linkedin.com/in/santino-cataldi/) |
| Matías Luhmann | [@Lumansito](https://github.com/Lumansito) | [matiasluhmann](https://www.linkedin.com/in/matiasluhmann/) |
| Tomás Wardoloff | [@Tomas-Wardoloff](https://github.com/Tomas-Wardoloff) | [tomaswardoloff](https://www.linkedin.com/in/tomaswardoloff/) |
| Marcos Godoy Quattoni | [@marcos-godoy](https://github.com/marcos-godoy) | [marcos-godoy-quattoni](https://www.linkedin.com/in/marcos-godoy-quattoni-52954722a/) |
| Matías Tomás Márquez | [@matipoli](https://github.com/matipoli) | [matias-tomas-marquez](https://www.linkedin.com/in/matias-tomas-marquez/) |

Universidad Tecnológica Nacional (UTN) — *Intelligent Systems*, 2026.
