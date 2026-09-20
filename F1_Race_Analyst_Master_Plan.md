# GridMind — Master Build Plan

> **Revision 2 (2026-09-20).** This revision replaces the batch-ingestion model of
> revision 1 with **on-demand, agent-triggered ingestion**, and fixes the deployment
> target. Decisions marked **[R2]** supersede the original brief.

## Project Goal

Build a full-stack AI-powered F1 race analyst called GridMind.

The product has three core experiences:

1. **Automated race reports**
2. **Natural-language F1 chatbot**
3. **Interactive F1 race-data website**

The user should be able to browse races, inspect data, read automatically generated reports, and ask questions in normal English.

Example:

> "Find me all drivers who finished in the top 10, started outside the top 5, and used a one-stop strategy."

The system should retrieve the correct structured data from PostgreSQL and return an understandable answer, ideally with a table.

---

# Product Architecture

```text
                  F1 DATA PROVIDERS
              FastF1 / OpenF1 / jolpica-f1
                         ^
                         | (pulled on demand)
                         |
                +------------------+
                | Python Ingestion |
                |   (job runner)   |
                +--------+---------+
                         |
                         v
                 +---------------+
                 | Supabase      |
                 | PostgreSQL    |
                 +-------+-------+
                         |
              +----------+----------+
              |                     |
              v                     v
      +---------------+      +---------------+
      | Analytics     |      | AI Agent      |
      | Engine        |      | / SQL Agent   |
      +-------+-------+      +-------+-------+
              |                      |
              +----------+-----------+
                         |
                         v
                    +---------+
                    | Groq LLM|
                    +----+----+
                         |
                         v
                    FastAPI
                         |
                         v
                  Next.js Website
```

Note the direction of the top arrow. **[R2]** Ingestion is not a scheduled batch that fills
the database ahead of time. It is a job the agent triggers when a question needs data
the database does not yet hold.

---

# Key Architecture Decisions

## 1. No Vector Database Initially

Do not introduce a vector database.

The majority of the application's data is:

- numerical
- categorical
- relational
- time-series
- structured

Examples:

- lap times
- finishing positions
- grid positions
- points
- tyres
- pit stops
- driver names
- constructors
- race dates
- session results

PostgreSQL is therefore the primary source of truth.

The LLM should use SQL and deterministic analytics to retrieve the data.

## 2. On-Demand Ingestion **[R2]**

The database starts empty. There is no season backfill.

When a user asks a question, the agent resolves which `(year, grand prix, session)`
the question needs, checks whether that session is already in PostgreSQL, and ingests
it only if it is missing.

```text
Question
   |
   v
Resolve (year, grand_prix, session)
   |
   v
Is it already ingested?
   |
   +-- yes --> query immediately
   |
   +-- no  --> run ingestion job --> query
```

Consequences that must be designed for:

- A cold question is slow. A first-time FastF1 session load takes roughly 30 seconds
  to 2 minutes. The Loading Pit is therefore a real progress indicator, not decoration.
- Ingestion must be an **async job** with observable state, not an inline blocking call.
- Two users asking about the same session concurrently must not both ingest it.
  Ingestion requires a lock per `(year, round, session_type)`.
- Questions that span a whole season (standings, "most points this year") cannot be
  answered by single-session ingestion. See decision 4.

## 3. Ingested Data Persists Permanently **[R2]**

Once a session is ingested it stays in PostgreSQL. Completed historical sessions are
immutable, so a cached session is always correct. The second request for a session is
instant.

The database grows monotonically with usage. This is intended — popular sessions warm
the cache for everyone.

## 4. Season-Level Questions Use a Standings Adapter **[R2]**

Season standings cannot be derived on demand, because deriving them would require
ingesting every race in the season.

Instead, route standings questions to a dedicated standings provider
(**jolpica-f1**, the free community successor to the retired Ergast API) with a single
cheap HTTP call, and cache the result. This keeps "who leads the championship?"
answerable without triggering a season-wide ingest.

Standings data is stored in the same `driver_standings` / `constructor_standings`
tables the schema already defines.

## 5. Sessions Are Whole, Not Segmented **[R2]**

Model these session types only:

```text
practice_1
practice_2
practice_3
qualifying
sprint
sprint_qualifying
race
```

Do **not** model Q1/Q2/Q3 or SQ1/SQ2/SQ3 as separate sessions. FastF1 returns
qualifying as a single session.

Exception: qualifying **results** carry each driver's Q1/Q2/Q3 lap times as ordinary
result columns. Store those three columns so "what was Norris's Q3 time?" still works.

## 6. Ingest Depth Excludes Telemetry **[R2]**

Per session, ingest:

- session results
- laps (lap time, sectors, compound, tyre life, speed trap)
- pit stops
- race control events

Do **not** ingest car telemetry channels (speed/throttle/brake/gear traces). Those are
millions of rows per session and are a deferred future feature.

---

# LLM Responsibilities

Use Groq as the preferred LLM provider, on a **free-tier model** **[R2]**.

The LLM should handle:

- natural-language understanding
- query planning
- entity resolution (which race, which driver, which session)
- SQL generation
- explanation
- report writing
- converting structured results into natural language

The LLM should **not** be responsible for:

- remembering factual race statistics
- inventing missing data
- performing unnecessary arithmetic
- being the database
- directly modifying the database

---

# Cost Control **[R2]**

The site is public and anonymous. Both the LLM and the upstream F1 API are costs an
unauthenticated visitor can run up. Design for cheapness from the start.

- Use a Groq free-tier model. Do not hard-code the model name; select it via
  `GROQ_MODEL` and verify availability at integration time.
- Groq free tier enforces requests-per-minute and tokens-per-day limits. The app must
  degrade gracefully when rate-limited rather than erroring opaquely.
- Minimise LLM round-trips per question. Prefer one planning call plus one answer call.
  Use recovery retries only on actual failure.
- Cache aggressively. An already-ingested session costs zero upstream requests.
- Rate-limit by IP on `/api/chat` and on ingestion triggers.
- Cap the number of concurrent ingestion jobs process-wide.
- Enforce a per-question ceiling on ingestion: if answering would require ingesting more
  than one or two sessions, ask the user to narrow the question instead.
- FastF1 itself is free and open-source. There is no paid tier to avoid. The cost
  surface is Groq tokens and hosting only.

---

# Agent Flow **[R2]**

```text
User Question
      |
      v
Understand Intent
      |
      v
Resolve Entities (year / grand prix / session / driver)
      |
      +---- ambiguous ----> ask user to clarify
      |
      v
Is required data in PostgreSQL?
      |
      +---- no ----> Trigger ingestion job
      |                    |
      |                    v
      |              Stream progress to client
      |                    |
      |                    v
      |              Job complete / failed
      |                    |
      +--------------------+
      |
      v
Create Query Plan
      |
      v
Generate SQL
      |
      v
Validate SQL
      |
      v
Execute Read-Only Query
      |
      v
Validate Results
      |
      +---- Error / Empty ----+
      |                       |
      |                       v
      |                  Recovery
      |                       |
      +-----------------------+
      |
      v
Generate Answer
      |
      v
Return text + structured data
```

The agent decides for itself which race and session a question needs, and whether that
data must be fetched first. The user never selects a filter before asking.

---

# Automated Report Flow **[R2]**

Reports are generated on two different triggers:

**Future races — automatic.** Once a race has concluded and its data becomes available
from the provider, a scheduled check ingests it and generates the report without anyone
asking.

**Historic races — on request.** Reports for past races are generated only when a user
asks for one, then stored permanently so the next reader gets it instantly.

```text
      [automatic]                    [on request]
Scheduled availability check      User requests report
            |                              |
            v                              v
      Ingest race session          Already ingested? --no--> ingest
            |                              |
            +--------------+---------------+
                           |
                           v
                 Data completeness check
                           |
                           v
                 Deterministic analytics
                           |
                           v
              Build structured race context
                           |
                           v
                         Groq
                           |
                           v
                    Generate report
                           |
                           v
                       Validate
                           |
                           v
              Store report in PostgreSQL
```

Reports should combine:

- hard statistics
- strategy information
- driver performance
- race events
- an LLM-generated narrative

All numbers should come from the database/analytics layer.

---

# Suggested User Experience

## Homepage

```text
GRIDMIND

Understand the race beyond the result.

[ Ask the Race Analyst ]

Latest Race
Australian Grand Prix

P1  Driver
P2  Driver
P3  Driver

[ Read Race Report ]
```

---

## Chat

```text
ASK THE RACE ANALYST

"Who had the best race pace?"

        v

Based on the available lap data, Driver A
had the strongest average race pace.

[comparison table]
```

The user can continue asking follow-up questions.

**[R2]** When a question requires data that is not yet ingested, the chat must show
staged progress rather than an undifferentiated spinner — see Loading Pit below.

---

# Loading Pit

The website should have a signature loading experience.

Whenever a major operation is taking place:

```text
             LOADING PIT

               o o o o o

          ANALYSING RACE DATA
```

Lights:

```text
1 -> 2 -> 3 -> 4 -> 5
```

Then all lights remain on briefly and switch off.

Play a short synthesized beep for each light using the Web Audio API.

Use an original implementation inspired by motorsport start lights rather than copying F1 broadcast graphics/audio.

The user must be able to mute the sounds.

Respect reduced-motion preferences.

Do not artificially delay fast API responses just to show the animation.

**[R2] The Loading Pit now carries real information.** Because a cold question triggers
ingestion, waits can legitimately run to a minute or more. The five lights should map to
observable backend stages rather than elapsed time:

```text
o  Resolving the session
o  Fetching timing data
o  Storing results and laps
o  Running analytics
o  Writing your answer
```

A warm question skips straight to the last stages and the animation stays brief.

---

# Technology Stack

## Backend

- Python 3.12+
- FastAPI
- PostgreSQL
- Supabase
- **SQLAlchemy 2.0 + Alembic** **[R2]**
- FastF1/OpenF1 adapter
- jolpica-f1 standings adapter **[R2]**
- Groq API
- Pydantic
- pytest

## Frontend

- Next.js
- TypeScript
- Tailwind CSS
- React
- Framer Motion
- Recharts
- Web Audio API

---

# Deployment **[R2]**

```text
Vercel                    Container host
+----------------+        +------------------------+
| Next.js        | -----> | FastAPI                |
| frontend       |  HTTPS | + ingestion job runner |
+----------------+        | + persistent FastF1    |
                          |   cache volume         |
                          +-----------+------------+
                                      |
                                      v
                              Supabase PostgreSQL
```

The frontend deploys to Vercel.

The backend does **not**. Vercel Python functions are a poor fit for this workload:

- FastF1 pulls in pandas, numpy and scipy, which sit awkwardly against the bundle limit
  and cold-start slowly.
- The filesystem is read-only apart from an ephemeral `/tmp`, so FastF1's cache — which
  is central to its performance — cannot persist. Every session would re-download.
- Execution time limits sit directly on top of typical cold-ingest durations.

Deploy the backend as a long-running container (Railway, Render or Fly) with a persistent
volume for the FastF1 cache. Keep the application host-agnostic so this can change.

The backend must be reachable from the Vercel deployment, so configure `CORS_ORIGINS`
for both the production and preview domains.

---

# Repository

```text
GridMind/
|
├── backend/
│   ├── app/
│   ├── tests/
│   ├── scripts/
│   ├── migrations/
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/          (supplied separately)
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── public/
│   └── package.json
│
├── README.md
└── docker-compose.yml
```

**[R2]** The frontend is provided by the project owner. Backend work and the
backend-to-frontend integration are the implementation scope.

---

# Development Phases **[R2]**

Phases 1–6 are backend. Phase 7 is integration with the supplied frontend.

## Phase 1 — Foundation

- create FastAPI application
- configuration via Pydantic Settings
- Supabase connection
- health endpoint

## Phase 2 — Database

Create relational schema for:

- seasons
- circuits
- races/events
- sessions
- drivers
- constructors
- session results
- laps
- pit stops
- race control events
- standings
- reports
- **ingestion jobs** **[R2]**

Add indexes and foreign keys. Manage with Alembic migrations.

## Phase 3 — On-Demand Ingestion **[R2]**

Implement:

```text
DataProvider
    |
    +-- FastF1
    |
    +-- OpenF1
    |
    +-- jolpica-f1 (standings)
```

Build:

```text
resolve -> check cache -> lock -> fetch -> normalize -> validate -> upsert -> verify -> release
```

Ingestion runs as an async job with a row in `ingestion_jobs` tracking state and stage.
Expose job state so the client can drive the Loading Pit.

Prove the pipeline on a single session before adding the agent on top.

## Phase 4 — Analytics

Build deterministic functions for:

- race classification
- points
- position changes
- fastest laps
- average pace
- tyre stints
- pit stops
- qualifying vs race
- driver comparison
- constructor comparison
- standings

Test against known data.

## Phase 5 — Chat Agent

Build:

```text
entity_resolver      [R2]
ingestion_gate       [R2]
planner
sql_generator
sql_validator
executor
recovery
answer_generator
```

Make the SQL database role read-only.

Implement retry/recovery for bad SQL.

## Phase 6 — Reports

Generate:

- race summary
- podium
- qualifying changes
- driver highlights
- strategy
- tyre analysis
- pit stops
- race story
- key statistics

Store reports in PostgreSQL. Wire both triggers: the scheduled check for newly available
races, and the on-request path for historic races.

## Phase 7 — Frontend Integration **[R2]**

Against the supplied frontend:

- confirm the API contract
- wire race, report and chat endpoints
- wire ingestion job progress into the Loading Pit
- loading / error / empty states
- deploy frontend to Vercel, backend to the container host
- test complete flows

```text
User -> Website -> Chat -> Agent -> (ingest?) -> SQL -> PostgreSQL -> Groq -> Website
```

and:

```text
Race concludes -> Scheduled check -> Ingestion -> Analytics -> Groq -> Report -> Website
```

---

# Important Engineering Principles

## 1. Database Is the Source of Truth

Do not allow the LLM to invent race data.

## 2. Deterministic Before Generative

If SQL/Python can calculate it reliably, do that first.

## 3. LLM for Reasoning and Communication

Use Groq to:

- understand questions
- resolve entities
- plan retrieval
- write SQL
- explain results
- write reports

## 4. Safe SQL

Only read queries should be allowed.

## 5. Recover Automatically

The agent should attempt controlled recovery from:

- SQL syntax errors
- schema misunderstandings
- empty results
- ambiguous questions
- provider failures
- **failed or timed-out ingestion jobs** **[R2]**

## 6. Keep Providers Replaceable

Do not tightly couple the entire application to Groq or one F1 data source.

## 7. Never Ingest More Than the Question Needs **[R2]**

Ingestion is the expensive operation. One question should trigger at most one or two
session ingests. If a question would require more, narrow it or ask the user to.

---

# Example Questions the Finished Product Should Handle

### Lookup

> Who won the 2026 Australian GP?

### Filtering

> Which drivers finished in the top 10 and started outside the top 5?

### Comparison

> Compare Norris and Leclerc's race pace.

### Strategy

> Which drivers used a one-stop strategy?

### Tyres

> How long did Verstappen run the hard tyres?

### Position Changes

> Who gained the most positions during the race?

### Season

> Who has scored the most points this season?

Answered via the standings adapter, not by ingesting the season. **[R2]**

### Multi-condition

> Show me drivers who finished in the top 5, gained at least 3 positions, and made no more than two pit stops.

### Explanatory

> Why did Driver X lose positions after the first pit stop?

For explanatory questions, distinguish database evidence from interpretation.

### Qualifying **[R2]**

> What was Norris's Q3 time?

Answered from the qualifying result columns, without modelling Q3 as its own session.

---

# Testing Requirements

Create tests for:

- entity resolution **[R2]**
- ingestion-gate decisions (ingest vs serve from cache) **[R2]**
- ingestion job locking and concurrency **[R2]**
- data ingestion
- duplicate prevention
- schema integrity
- analytics calculations
- SQL safety
- SQL recovery
- ambiguous questions
- empty results
- chatbot responses
- report factual consistency
- API endpoints

Create a representative evaluation set of at least 30–50 questions.

Measure:

- entity-resolution accuracy **[R2]**
- SQL correctness
- answer correctness
- hallucination rate
- recovery success
- latency, split by cold (ingest required) and warm (cached) **[R2]**
- report factual consistency

---

# Future Features

Do not implement these in the first version unless the core product is stable:

- live race tracking
- WebSockets
- voice interface
- user accounts
- personalized dashboards
- predictive race simulations
- race outcome prediction
- advanced telemetry replay
- multi-agent architecture
- vector search
- mobile app
- season backfill / batch ingestion **[R2]**

The first version should prioritize reliable structured-data analysis and a polished user experience.

---

# Claude Code Instructions

Implement this project incrementally.

Before writing significant code:

1. Inspect the existing repository.
2. Create a clear implementation checklist.
3. Build the backend first; integrate the supplied frontend afterwards.
4. Do not make assumptions about unavailable APIs or model names.
5. Use environment variables for credentials.
6. Do not expose secrets to the frontend.
7. Run tests after each major backend feature.
8. Fix errors before continuing.
9. Keep the architecture simple enough for one developer to understand and maintain.

When a third-party API's current behavior or model availability matters, verify its current documentation rather than relying on memory. This applies especially to the Groq model catalogue and to FastF1, whose data sources have changed since the Ergast API was retired.

The final README should explain:

- architecture
- setup
- environment variables
- Supabase setup
- how on-demand ingestion works and why the first question about a session is slow
- Groq configuration and free-tier rate limits
- running backend
- running frontend
- deployment (Vercel frontend, container backend)
- testing
- generating reports
- using the chatbot
- project limitations
