# GridMind — Backend Implementation Plan

> **Revision 2 (2026-09-20).** Revision 1 assumed a pre-populated database filled by
> batch season ingestion. That model is replaced by **on-demand, agent-triggered
> ingestion**. Sections marked **[R2]** are new or rewritten.

## 1. Goal

Build a Python backend for GridMind, an AI-powered F1 race analyst that:

1. Fetches and stores structured F1 data in PostgreSQL hosted on Supabase, **on demand,
   in response to user questions**. **[R2]**
2. Generates automated race summaries and detailed race reports.
3. Provides a natural-language chatbot that can answer questions about races, drivers, constructors, sessions, lap times, tyre usage, pit stops, positions, and other stored data.
4. Uses an LLM primarily for planning, entity resolution, explanation, and report generation — not as the source of numerical truth.
5. Uses SQL against PostgreSQL for quantitative/categorical questions.
6. Can recover from invalid SQL, missing data, failed ingestion, tool failures, and ambiguous questions.
7. Exposes a clean API for the frontend.
8. Runs cheaply enough to sit behind a public, unauthenticated website. **[R2]**

The system should **not use a vector database initially**. F1 race data is primarily structured, numerical, categorical, and relational, so PostgreSQL + SQL is the primary retrieval mechanism.

---

## 2. Recommended Stack

### Backend
- Python 3.12+
- FastAPI
- Pydantic / Pydantic Settings
- **SQLAlchemy 2.0 + Alembic** — decided; ORM models for ingestion and repositories,
  Alembic for versioned migrations, raw SQL for the agent's read path **[R2]**
- PostgreSQL on Supabase
- httpx for external API calls
- **An in-process async job runner for ingestion** (asyncio tasks plus a database-backed
  job table). Keep the architecture compatible with a real queue later. **[R2]**
- **APScheduler** or an equivalent in-process scheduler for the automatic post-race
  report trigger **[R2]**
- pytest
- Ruff
- mypy where practical

### LLM
Use Groq as the preferred provider, on a **free-tier model**. **[R2]**

Create an LLM abstraction so the application is not tightly coupled to Groq:

```text
LLMProvider
├── GroqProvider
└── OptionalFallbackProvider
```

The backend should be able to switch models through environment variables rather than code changes.

Do not hard-code a model name. Use:

```env
GROQ_API_KEY=
GROQ_MODEL=
```

Verify the currently available Groq models when implementing the integration rather than
assuming a model name. Pick a free-tier model capable of structured tool calling and
report generation.

**[R2]** Groq's free tier enforces requests-per-minute and tokens-per-day limits. The
provider abstraction must surface rate-limit errors distinctly from other failures so
the API can return a clear "try again shortly" response rather than a generic 500.

### Data
Keep the data ingestion layer provider-agnostic:

```text
DataProvider
├── FastF1 adapter        (session results, laps, pit stops, race control)
├── OpenF1 adapter        (optional/secondary)
└── jolpica-f1 adapter    (season standings)   [R2]
```

**[R2] Notes on the providers:**

- **FastF1** is free and open-source. There is no paid tier. It caches aggressively to
  a local directory, and that cache is essential to performance — the deployment must
  give it a persistent volume.
- **Ergast is retired.** FastF1 no longer sources standings from it. Season standings
  come from **jolpica-f1**, the free community successor, which is rate-limited and
  should be called sparingly and cached.
- On-demand single-session ingestion cannot compute season standings. Standings
  questions must route to the standings adapter, not to the ingestion pipeline.

---

## 3. High-Level Architecture **[R2]**

```text
                         External F1 Data
                    FastF1 / OpenF1 / jolpica-f1
                                 ^
                                 | fetch, only when needed
                                 |
                        +--------+---------+
                        | Ingestion Job    |
                        | Runner + Locking |
                        +--------+---------+
                                 |
                                 v
                        +------------------+
                        | PostgreSQL       |
                        | Supabase         |
                        +--------+---------+
                                 |
                  +--------------+--------------+
                  |                             |
                  v                             v
        +------------------+           +-------------------+
        | Query/Analytics  |           | Report Generator  |
        | Service          |           |                   |
        +--------+---------+           +---------+---------+
                 |                               |
                 +---------------+---------------+
                                 |
                                 v
                         +---------------+
                         | LLM / Groq    |
                         +-------+-------+
                                 |
                                 v
                         +---------------+
                         | FastAPI API   |
                         +-------+-------+
                                 |
                                 v
                             Frontend
```

The agent sits above this and decides whether the ingestion job runner needs to run
before a query can be answered.

---

## 4. Repository Structure **[R2]**

```text
GridMind/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   │
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── health.py
│   │   │   │   ├── races.py
│   │   │   │   ├── drivers.py
│   │   │   │   ├── reports.py
│   │   │   │   ├── jobs.py          [R2] ingestion job status
│   │   │   │   └── chat.py
│   │   │   └── schemas/
│   │   │       ├── chat.py
│   │   │       ├── race.py
│   │   │       ├── job.py           [R2]
│   │   │       └── report.py
│   │   │
│   │   ├── db/
│   │   │   ├── database.py
│   │   │   ├── models.py
│   │   │   └── repositories/
│   │   │
│   │   ├── ingestion/
│   │   │   ├── base.py
│   │   │   ├── fastf1_provider.py
│   │   │   ├── openf1_provider.py
│   │   │   ├── standings_provider.py    [R2] jolpica-f1
│   │   │   ├── normalizer.py
│   │   │   ├── pipeline.py
│   │   │   ├── jobs.py                  [R2] job runner + state
│   │   │   └── locks.py                 [R2] per-session advisory locks
│   │   │
│   │   ├── analytics/
│   │   │   ├── race_stats.py
│   │   │   ├── driver_stats.py
│   │   │   ├── constructor_stats.py
│   │   │   ├── tyre_stats.py
│   │   │   └── pitstop_stats.py
│   │   │
│   │   ├── agent/
│   │   │   ├── orchestrator.py
│   │   │   ├── entity_resolver.py       [R2]
│   │   │   ├── ingestion_gate.py        [R2]
│   │   │   ├── planner.py
│   │   │   ├── sql_generator.py
│   │   │   ├── sql_validator.py
│   │   │   ├── executor.py
│   │   │   ├── answer_generator.py
│   │   │   └── recovery.py
│   │   │
│   │   ├── reports/
│   │   │   ├── generator.py
│   │   │   ├── scheduler.py             [R2] post-race auto trigger
│   │   │   ├── templates.py
│   │   │   └── sections.py
│   │   │
│   │   └── llm/
│   │       ├── base.py
│   │       ├── groq.py
│   │       └── prompts.py
│   │
│   ├── tests/
│   ├── scripts/
│   │   ├── ingest_session.py        [R2] admin/debug tool, single session
│   │   └── generate_report.py
│   ├── migrations/                  Alembic
│   ├── requirements.txt
│   ├── Dockerfile                   [R2]
│   └── .env.example
│
├── frontend/         (supplied by the project owner)
├── README.md
└── docker-compose.yml
```

**[R2]** `scripts/ingest_season.py` is removed. Season backfill is out of scope. A
single-session script remains as a debugging aid, not as a production path.

Keep the backend independently runnable during development.

---

## 5. Database Design

Use relational tables rather than storing everything as large JSON blobs.

### seasons
- id
- year

### circuits
- id
- name
- location
- country
- latitude
- longitude

### meetings / events
- id
- season_id
- circuit_id
- round_number
- event_name
- event_date

### sessions
- id
- meeting_id
- session_type
- session_date
- **ingested_at** — null until the session has been successfully ingested **[R2]**

Allowed `session_type` values — whole sessions only: **[R2]**

```text
practice_1
practice_2
practice_3
qualifying
sprint
sprint_qualifying
race
```

Q1/Q2/Q3 and SQ1/SQ2/SQ3 are **not** session types.

### drivers
- id
- driver_code
- first_name
- last_name
- full_name
- nationality
- permanent_number

### constructors
- id
- name

### driver_seasons
- season_id
- driver_id
- constructor_id

### session_results
- id
- session_id
- driver_id
- constructor_id
- position
- points
- grid_position
- status
- fastest_lap
- fastest_lap_time
- total_laps
- **q1_time_ms** — nullable, populated for qualifying sessions **[R2]**
- **q2_time_ms** — nullable **[R2]**
- **q3_time_ms** — nullable **[R2]**

**[R2]** These three columns preserve segment-level qualifying answers without modelling
segments as sessions.

### laps
- id
- session_id
- driver_id
- lap_number
- lap_time_ms
- sector_1_ms
- sector_2_ms
- sector_3_ms
- speed_trap
- compound
- tyre_life

### pit_stops
- id
- session_id
- driver_id
- lap
- duration_ms

### race_control_events
- id
- session_id
- timestamp
- event_type
- message
- driver_id nullable

### driver_standings
- season_id
- round_number
- driver_id
- position
- points
- **fetched_at** — standings come from jolpica-f1 and are cached, so record freshness **[R2]**

### constructor_standings
- season_id
- round_number
- constructor_id
- position
- points
- **fetched_at** **[R2]**

### reports
- id
- meeting_id
- report_type
- generated_at
- model
- content
- metadata
- **trigger** — `automatic` or `on_request` **[R2]**

### ingestion_jobs **[R2]**

The table that makes on-demand ingestion observable and safe.

- id
- season_year
- round_number
- session_type
- status — `pending`, `running`, `succeeded`, `failed`, `skipped_cached`
- stage — `resolving`, `fetching`, `normalizing`, `storing`, `verifying`
- progress_percent — nullable
- started_at
- finished_at
- error_message — nullable
- rows_written — nullable
- requested_by_conversation_id — nullable

Unique constraint on `(season_year, round_number, session_type)` where status is
`pending` or `running`. This is what prevents two users triggering the same ingest
concurrently.

### Indexes

Add indexes for:
- season_id
- meeting_id
- session_id
- driver_id
- constructor_id
- lap_number
- event_date
- `sessions.ingested_at` **[R2]**
- `ingestion_jobs (season_year, round_number, session_type)` **[R2]**

Use foreign keys and appropriate unique constraints. Manage all schema through Alembic.

---

## 6. On-Demand Ingestion **[R2]**

This section replaces revision 1's batch pipeline entirely.

### Pipeline

```text
resolve (year, round, session_type)
   |
   v
check sessions.ingested_at  -- already present? --> return immediately
   |
   v
acquire lock for (year, round, session_type)
   |
   +-- lock held by another job --> attach to that job, stream its progress
   |
   v
create ingestion_jobs row (status=running)
   |
   v
fetch     (FastF1, via persistent cache)
   |
   v
validate  (reject corrupt/incomplete payloads)
   |
   v
normalize (provider shapes -> our schema)
   |
   v
upsert    (idempotent, transactional)
   |
   v
verify    (row counts, referential integrity)
   |
   v
set sessions.ingested_at, job status=succeeded, release lock
```

### Requirements

- **Idempotent.** Running ingestion twice must not create duplicate races, drivers, laps,
  or pit stops. Use natural keys and upserts.
- **Locked.** Concurrent requests for the same session must produce one job, not two.
  Use a PostgreSQL advisory lock keyed on the session tuple, backed by the unique
  constraint on `ingestion_jobs`.
- **Asynchronous.** The HTTP request that triggers ingestion must not block for the full
  30s–2min duration. Return a job id; let the client poll or subscribe.
- **Observable.** Every stage transition updates the job row so the Loading Pit can show
  real progress.
- **Bounded.** Cap concurrent ingestion jobs process-wide. Reject or queue beyond the cap.
- **Timeout-guarded.** A job that exceeds a configured ceiling is marked `failed` and the
  lock released, so one stuck fetch does not block that session forever.
- **Transactional.** A failed ingest must leave no partial session behind. Either
  `ingested_at` is set and the data is complete, or nothing is visible.
- Store source/provider information where useful.
- Log ingestion duration and record counts.
- Handle incomplete sessions — a session in progress or with missing laps should be
  marked as such rather than silently stored as complete.
- Handle API/network errors with bounded retries.
- Do not silently insert corrupt data.
- Validate timestamps and driver/session relationships.

### Admin/debug command

```bash
python -m scripts.ingest_session --year 2025 --round 1 --session race
```

Re-ingesting a session must be safe. Provide an explicit `--force` flag for the rare case
where a provider corrects data after the fact.

### What the pipeline does not do

- No season backfill.
- No telemetry channels.
- No standings computation — see section 6a.

---

## 6a. Standings Adapter **[R2]**

Season-level questions ("who leads the championship?", "who has the most points this
season?") cannot be answered from on-demand single-session ingestion, because that would
require every race in the season.

Route them separately:

```text
Standings question
      |
      v
Check driver_standings / constructor_standings freshness
      |
      +-- fresh --> serve from PostgreSQL
      |
      v
One HTTP call to jolpica-f1
      |
      v
Upsert standings, set fetched_at
      |
      v
Serve
```

jolpica-f1 is rate-limited. Cache standings with a sensible TTL (a season's standings
only change after a race weekend) and never call it inside a loop.

---

## 7. Analytics Layer

Do not ask the LLM to calculate obvious statistics.

Implement deterministic analytics functions for things such as:

- race finishing order
- points gained
- position changes
- average lap time
- fastest lap
- stint duration
- tyre compound usage
- pit-stop duration
- qualifying-to-race position changes
- driver head-to-head results
- constructor performance
- DNF rate
- safety-car periods
- lap-by-lap gaps where available

Example:

```python
get_race_summary(race_id)
get_driver_race_stats(race_id, driver_id)
compare_drivers(race_id, driver_a, driver_b)
get_tyre_stints(race_id, driver_id)
get_constructor_performance(season_id)
```

This makes numerical answers deterministic and reduces hallucinations.

**[R2]** Analytics functions operate only on already-ingested sessions. They must never
trigger ingestion themselves — that decision belongs to the ingestion gate in the agent.

---

## 8. Natural-Language Chatbot

The chatbot should accept questions such as:

> "Which drivers finished in the top 5 at the 2025 Australian GP?"

> "Compare Norris and Leclerc's race pace."

> "Which driver gained the most positions from the grid?"

> "What tyres did Verstappen use and when did he pit?"

> "What was Norris's Q3 time?"

> "Who has scored the most points this season?"

> "Why did Ferrari struggle in this race?"

The last question requires the system to distinguish between measurable evidence and interpretation.

**[R2]** The user never selects a race before asking. The agent infers the race and
session from the question, and fetches the data if it is missing. A question with no
identifiable race should fall back to a clarifying question, not a guess.

---

## 9. Agent Architecture **[R2]**

Use a controlled agent loop rather than giving the LLM unrestricted database access.

```text
User Question
     |
     v
Intent classification
     |
     +-- standings intent --> standings adapter --> answer generation
     |
     v
Entity Resolution
  (year, grand prix, session_type, drivers)
     |
     +-- ambiguous --> clarifying question to user, stop
     |
     v
Ingestion Gate
  Is the required session ingested?
     |
     +-- yes --> continue
     |
     +-- no  --> would this need more than the ingest budget?
     |              |
     |              +-- yes --> ask user to narrow the question, stop
     |              |
     |              +-- no  --> trigger ingestion job, stream progress,
     |                          wait for completion
     |
     v
Query Planning
     |
     v
Generate SQL
     |
     v
Validate SQL
     |
     v
Execute read-only SQL
     |
     v
Check results
     |
     +---- insufficient/error ----> recovery
     |
     v
LLM answer generation
     |
     v
Final response
```

### Entity resolution

Turns natural language into a concrete session tuple.

- "the last race" → resolve against the calendar, not the ingested data
- "Monza" → circuit name to round number for the inferred season
- "last year" → relative date arithmetic done in Python, not by the LLM
- Driver nicknames and surnames → canonical driver records
- Missing year → default to the current season, and say so in the answer

Ambiguity is resolved by asking, not guessing. "Who won at Silverstone?" without a year
should ask which year rather than assuming.

### Ingestion gate

The gate is what keeps the system cheap. It enforces:

- at most one or two session ingests per question
- a hard refusal for questions that would require a season-wide ingest, with a suggestion
  to ask about standings or a specific race instead
- immediate pass-through when the session is already cached

### What the LLM is given

1. Database schema.
2. Allowed tables/columns.
3. SQL rules.
4. User question.
5. Relevant conversation context.
6. Query results.
7. **Which sessions are currently available in the database.** **[R2]**

Never give the LLM unrestricted write access. The chatbot database role is read-only.

**[R2]** The LLM cannot trigger ingestion directly. It proposes an entity resolution;
the ingestion gate — ordinary Python — decides whether a job runs.

---

## 10. SQL Safety

The generated SQL must be validated before execution.

Reject:

```sql
INSERT
UPDATE
DELETE
DROP
ALTER
TRUNCATE
CREATE
GRANT
REVOKE
```

Only permit read operations.

Prefer parameterized SQL.

Set:
- statement timeout
- result row limits where appropriate
- query logging
- maximum retry count

Do not simply execute arbitrary SQL returned by an LLM.

**[R2]** The read-only role is a separate Supabase/PostgreSQL role from the one the
ingestion pipeline uses. Ingestion writes; the agent reads. Enforce this at the database
level with grants, not only in application code.

---

## 11. Query Recovery

The agent should recover from failures.

```text
Question
  ↓
SQL generation
  ↓
SQL error
  ↓
Explain error to planner
  ↓
Regenerate SQL
  ↓
Retry
```

Limit retries to 2–3.

Also recover from:

- empty result set
- ambiguous driver name
- ambiguous race name
- unavailable data
- invalid date
- unsupported question
- LLM timeout
- **LLM rate-limit rejection** **[R2]**
- provider error
- **failed ingestion job** **[R2]**
- **ingestion timeout** **[R2]**

If data is unavailable, say so rather than inventing an answer.

**[R2]** Ingestion failures need their own user-facing message. "The timing data for that
session could not be retrieved" is a different problem from "no driver matched that name",
and the user should be able to tell them apart.

**[R2]** Recovery retries cost LLM tokens. Retry on genuine failure only — never on a
merely unexpected but valid result.

---

## 12. Report Generator

### Triggers **[R2]**

Reports are produced two different ways:

**Automatic — future races.** A scheduled check looks for races that have concluded and
whose data has become available from the provider. When one appears, ingest the race
session and generate its report unprompted.

**On request — historic races.** Reports for past races are generated only when a user
asks. This avoids spending tokens on reports nobody reads. Once generated, the report is
stored permanently and served instantly thereafter.

The scheduler should run infrequently (checking a handful of times a day around race
weekends is sufficient) and must not fire during the rest of the week.

### Suggested report

#### Race Overview
- race winner
- podium
- fastest lap
- total laps
- major race status/events

#### Qualifying vs Race
- starting positions
- biggest gains
- biggest losses

#### Driver Performance
- top performers
- notable drives
- DNFs
- pace metrics

#### Strategy
- tyre compounds
- stint lengths
- pit stops
- notable strategy changes

#### Race Story
LLM-generated narrative based only on retrieved facts.

#### Key Numbers
Use deterministic values from SQL.

#### Takeaways
Short evidence-backed observations.

The LLM should not invent facts or statistics. Pass structured data into the report prompt.

Store generated reports in PostgreSQL.

---

## 13. Report Generation Pipeline **[R2]**

```text
      [automatic]                        [on request]
Scheduler finds concluded race      User requests report for race
            |                                    |
            v                                    v
    Ingest race session              Session ingested? --no--> ingest
            |                                    |
            +------------------+-----------------+
                               |
                               v
                    Check data completeness
                               |
                               v
                    Run deterministic analytics
                               |
                               v
                       Build report context
                               |
                               v
                             Groq
                               |
                               v
                  Validate generated report
                               |
                               v
                         Store report
```

Use a structured intermediate representation:

```json
{
  "race": {},
  "podium": [],
  "qualifying_changes": [],
  "driver_highlights": [],
  "strategy": [],
  "key_statistics": []
}
```

Then ask the LLM to turn this into readable prose.

**[R2]** Report generation is the most token-expensive operation in the system. Generate
a given report once, store it, and never regenerate unless explicitly asked.

---

## 14. API **[R2]**

```text
GET  /health

GET  /api/seasons/{year}/calendar        calendar, no ingestion required
GET  /api/races                          races known to the database
GET  /api/races/{race_id}
GET  /api/races/{race_id}/results
GET  /api/races/{race_id}/stats
GET  /api/races/{race_id}/report

POST /api/races/{race_id}/report/generate

GET  /api/standings/{year}/drivers       via standings adapter
GET  /api/standings/{year}/constructors

POST /api/ingest                         trigger a session ingest, returns job id
GET  /api/jobs/{job_id}                  poll ingestion job state
GET  /api/jobs/{job_id}/stream           SSE progress for the Loading Pit

POST /api/chat
```

### Chat request

```json
{
  "message": "Who had the fastest race pace?",
  "conversation_id": "optional-id"
}
```

### Chat response

```json
{
  "answer": "...",
  "data": [],
  "sources": [],
  "query_type": "race_comparison",
  "resolved_entities": {
    "year": 2025,
    "round": 14,
    "grand_prix": "Italian Grand Prix",
    "session_type": "race"
  },
  "ingestion": {
    "required": true,
    "job_id": "..."
  },
  "needs_clarification": false,
  "clarifying_question": null
}
```

**[R2] Notes on the contract:**

- `resolved_entities` lets the frontend show what the agent decided it was asked about,
  which matters when the agent had to infer a season.
- `ingestion.job_id`, when present, is what the Loading Pit polls or streams.
- `needs_clarification` is how the agent asks "which year did you mean?" without
  pretending to have an answer.
- The chat endpoint should return promptly with a job id when ingestion is required,
  rather than holding the connection open for two minutes. The frontend follows up.

The frontend uses `data` to render tables/charts.

### Rate limiting **[R2]**

The site is public and anonymous. Apply per-IP rate limits to `/api/chat`,
`/api/ingest`, and `/api/races/{id}/report/generate`. These are the three endpoints that
cost money.

---

## 15. Conversation Context **[R2]**

Keep conversation memory **in process**. Conversations are not persisted and are expected
to vanish when the container restarts or redeploys. This is an accepted v1 tradeoff.

Hold in memory, keyed by conversation id:

- user message
- assistant response
- resolved entities from previous turns (so "and Leclerc?" works as a follow-up)
- timestamp

Requirements:

- Bound the store — evict by age and by total conversation count, so an in-memory map
  cannot grow without limit on a public site.
- Do not store personal information.
- Provide only limited recent context to the agent, to keep token use down.
- Do not depend on conversation memory for factual race data; query PostgreSQL again.

Because there is no persistence, the frontend must handle a conversation id that the
backend no longer recognises by starting a fresh conversation rather than erroring.

---

## 16. Prompt Design

Create separate prompts for:

### Entity Resolver **[R2]**
Extract year, grand prix, session type and drivers from the question. Return structured
output. Flag ambiguity explicitly rather than guessing.

### Planner
Determine:
- intent
- entities
- required data
- query strategy

### SQL Generator
Generate only PostgreSQL SELECT queries.

### Answer Generator
Explain results naturally and clearly.

### Report Generator
Produce a polished race report using only supplied facts.

Prompts should explicitly instruct the model:

```text
Never invent a statistic.
Never assume a value that is not present in the supplied data.
If the query results are insufficient, state that the available data is insufficient.
Do not perform calculations that can be obtained deterministically from SQL.
If the question does not identify a specific race clearly, ask which race is meant.
```

**[R2]** Keep prompts tight. On a free-tier model with token-per-day limits, a bloated
schema dump in every prompt is a real cost. Send only the tables relevant to the
resolved intent.

---

## 17. Testing

Create tests for:

### Entity resolution **[R2]**
- explicit year and race
- relative references ("last race", "last year")
- circuit nickname to round mapping
- missing year handling
- genuinely ambiguous questions producing a clarifying question, not a guess

### Ingestion gate **[R2]**
- cached session is served without a job
- missing session triggers exactly one job
- a question requiring too many sessions is refused
- concurrent identical requests produce one job, not two
- failed job produces a distinct user-facing error

### Ingestion
- duplicate prevention
- missing fields
- malformed data
- partial session
- re-ingestion safety
- transactional rollback leaves no partial session **[R2]**

### SQL Agent
- correct SQL
- dangerous SQL rejection
- invalid SQL recovery
- empty result handling
- ambiguous entity handling

### Analytics
- known race calculations
- position changes
- tyre stint calculations
- points calculations

### Standings adapter **[R2]**
- fresh cache is served without an HTTP call
- stale cache triggers exactly one call

### Reports
- factual consistency
- required sections
- no invented statistics
- automatic vs on-request trigger paths **[R2]**

### Chat
Create at least 30 representative questions covering:

- simple lookup
- aggregation
- comparison
- temporal question
- driver question
- constructor question
- tyre question
- qualifying segment question **[R2]**
- pit stop question
- strategy question
- season standings question **[R2]**
- unsupported question
- ambiguous question

**[R2]** The evaluation set must run against a fixture database rather than triggering
live ingestion, so tests are fast, deterministic and free.

---

## 18. Observability

Log:

- request ID
- question
- resolved entities **[R2]**
- ingestion decision (cached / job triggered / refused) **[R2]**
- ingestion job id, duration, stage timings, rows written **[R2]**
- selected intent
- generated SQL
- SQL execution time
- result row count
- LLM model
- LLM latency
- **LLM token usage, to track free-tier budget** **[R2]**
- retry count
- errors

Do not log API keys or sensitive data.

---

## 19. Environment **[R2]**

Create `.env.example`:

```env
# Database
DATABASE_URL=
DATABASE_URL_READONLY=
SUPABASE_URL=
SUPABASE_ANON_KEY=

# LLM
GROQ_API_KEY=
GROQ_MODEL=

# Ingestion
FASTF1_CACHE_DIR=/data/fastf1-cache
MAX_CONCURRENT_INGESTION_JOBS=2
INGESTION_JOB_TIMEOUT_SECONDS=300
MAX_SESSIONS_PER_QUESTION=2

# Standings
JOLPICA_BASE_URL=
STANDINGS_CACHE_TTL_HOURS=24

# Conversations
CONVERSATION_TTL_MINUTES=60
MAX_CONVERSATIONS_IN_MEMORY=500

# Reports
AUTO_REPORT_ENABLED=true
AUTO_REPORT_CHECK_CRON=

# API
CORS_ORIGINS=http://localhost:3000
RATE_LIMIT_CHAT_PER_MINUTE=
RATE_LIMIT_INGEST_PER_HOUR=
```

Use environment variables for all credentials and configuration.

`DATABASE_URL_READONLY` is the role the SQL agent uses. It must have SELECT grants only.

---

## 20. Deployment **[R2]**

The backend runs as a **long-running container** — Railway, Render or Fly — not on Vercel
serverless functions.

Reasons Vercel does not work for this backend:

- FastF1 pulls in pandas, numpy and scipy, a heavy dependency tree against the function
  bundle limit, with slow cold starts.
- The filesystem is read-only apart from an ephemeral `/tmp`. FastF1's cache cannot
  persist, so every session would re-download from the timing API — the single worst
  outcome for both latency and cost.
- Function execution limits sit directly on top of typical cold-ingest durations.
- The in-process job runner and report scheduler both need a process that stays alive.

Requirements for the container host:

- a **persistent volume** mounted at `FASTF1_CACHE_DIR`
- a process that is not scaled to zero, or the report scheduler will not fire
- health check wired to `/health`
- `CORS_ORIGINS` configured for the Vercel production and preview domains

Provide a `Dockerfile` and keep the application host-agnostic.

The Next.js frontend deploys separately to Vercel and talks to this backend over HTTPS.

---

## 21. Implementation Order **[R2]**

1. Repository structure.
2. Configuration (Pydantic Settings).
3. Supabase PostgreSQL connection; separate read-only role.
4. Database schema and Alembic migrations, including `ingestion_jobs`.
5. Data provider abstraction.
6. FastF1 single-session ingestion pipeline (synchronous first, to prove correctness).
7. Ingestion job runner, locking, and job status endpoints.
8. Analytics functions.
9. FastAPI race endpoints.
10. Standings adapter and endpoints.
11. Groq abstraction, with rate-limit handling.
12. Entity resolver.
13. Ingestion gate.
14. SQL agent.
15. SQL validation and recovery.
16. Chat endpoint, including job-id handoff and clarifying questions.
17. Report generator; on-request path first.
18. Report scheduler; automatic path.
19. Rate limiting.
20. Tests throughout, with a fixture database.
21. Dockerfile and deployment setup.
22. Frontend integration.
23. README.

Do not build everything in one giant implementation step.

After each major stage, run tests and fix errors before proceeding.

---

## 22. Definition of Done **[R2]**

The backend is complete when:

- A question about an un-ingested session triggers exactly one ingestion job and is
  answered correctly once it finishes.
- A repeat question about that session is answered immediately from PostgreSQL with no
  upstream request.
- Concurrent identical questions produce one ingestion job, not two.
- Re-running ingestion does not duplicate records.
- A failed ingestion leaves no partial session and produces a clear user-facing error.
- Ingestion job progress is observable through the API in a form the Loading Pit can use.
- Ambiguous questions produce a clarifying question rather than a guess.
- Questions that would require a season-wide ingest are refused with a useful suggestion.
- Season standings questions are answered through the standings adapter without ingesting
  the season.
- Qualifying segment times (Q1/Q2/Q3) are answerable from result columns.
- Race statistics can be queried deterministically.
- `/api/chat` understands normal English questions.
- The agent can generate and safely execute SQL.
- SQL failures trigger controlled retries.
- The agent cannot execute destructive SQL, enforced by database grants.
- Reports generate automatically for newly concluded races and on request for historic
  ones, and are stored and retrievable.
- The LLM does not invent unavailable statistics.
- Rate limiting protects the LLM and upstream provider from an anonymous visitor.
- API documentation is available through FastAPI.
- Automated tests cover entity resolution, the ingestion gate, ingestion, analytics,
  SQL safety, and chatbot behavior, and run without live network calls.
