# GridMind

An AI race analyst for Formula 1. Ask a question in plain English ("Who gained
the most places at Spa last year?") and GridMind works out which race you mean,
fetches that session's timing data if it hasn't stored it yet, queries it with
SQL, and answers with a table, a chart and its sources. It also shows race
pages (classification, lap pace, tyre strategy, pit stops, race control) and
writes a race report after each Grand Prix.

Every number comes from stored timing data. If the data can't answer a
question, GridMind says so rather than guessing.

## How it works

- **On-demand ingestion.** The database starts empty. The first request for a
  session (a race, qualifying, a sprint or a practice) fetches it through
  [FastF1](https://github.com/theOehrly/Fast-F1) and stores results, laps, pit
  stops and race control messages. That takes 20 seconds to 2 minutes, and the
  "Loading Pit" shows each real backend stage. After that the session is served
  from Postgres. Seasons from 2018 onward are supported.
- **The chat agent** runs one question through these steps:
  1. The LLM transcribes which race, session and drivers are mentioned, and
     Python matches them to the calendar. If that's ambiguous, it asks a
     clarifying question.
  2. It fetches any missing session and hands the frontend a job id to follow.
  3. The LLM writes SQL, which is validated, runs as a read-only database role,
     and is retried if it fails.
  4. The LLM writes the answer from the query results.
- **Standings** come from [jolpica-f1](https://github.com/jolpica/jolpica-f1),
  the successor to the Ergast API, and are cached in Postgres. They don't
  require fetching the season.
- **Race reports** are built from facts computed in Python. The LLM writes the
  prose, and the numbers in it are checked against those facts. A report is
  written automatically in the days after each race, or on request for any
  past race.

| Part | Stack | Hosting |
| --- | --- | --- |
| `frontend/` | Next.js 16, React 19, TypeScript, Tailwind | Vercel |
| `backend/` | FastAPI, SQLAlchemy 2 (async, psycopg 3), Alembic, FastF1 | A long-running container (Railway, Render or Fly) |
| Database | Postgres on [Neon](https://neon.tech), schema `gridmind` | Neon |
| LLM | [Groq](https://console.groq.com), `openai/gpt-oss-20b` or `-120b` | Groq |

## Running locally

You need Python 3.12 or newer (3.13 is what the tests run on),
[uv](https://docs.astral.sh/uv/), Node 24, and a Neon project. A Groq API key is
optional: without one, everything except chat and report writing works.

### 1. Database

Use Neon's **direct** endpoint for both URLs, not the `-pooler` host. The pooler
runs PgBouncer in transaction mode, which breaks prepared statements, and the
backend refuses to start with it.

The app uses two roles. The owner role (`neondb_owner`) runs migrations and
ingestion. A separate read-only role runs the SQL the agent writes, so the
agent cannot change data even if its SQL tries to. Create the schema and the
read-only role in the Neon SQL editor, as the owner:

```sql
CREATE SCHEMA gridmind AUTHORIZATION neondb_owner;

-- Create the role in SQL, not in the console's Roles tab: console-created
-- roles are members of neon_superuser and could write despite these grants.
CREATE ROLE gridmind_readonly WITH LOGIN PASSWORD '<a strong password>';
GRANT CONNECT ON DATABASE neondb TO gridmind_readonly;
GRANT USAGE ON SCHEMA gridmind TO gridmind_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA gridmind
    GRANT SELECT ON TABLES TO gridmind_readonly;
ALTER ROLE gridmind_readonly SET search_path = gridmind;
ALTER ROLE gridmind_readonly SET statement_timeout = '10s';
ALTER ROLE gridmind_readonly SET idle_in_transaction_session_timeout = '30s';
```

The default privileges cover every table the migrations create. If the tables
already existed before you created the role, also run
`GRANT SELECT ON ALL TABLES IN SCHEMA gridmind TO gridmind_readonly;`.

### 2. Backend

```bash
cd backend
uv venv
uv pip install -e ".[dev]"
cp .env.example .env          # then fill it in; see the comments in the file
.venv/Scripts/python -m alembic upgrade head    # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m app                     # serves http://127.0.0.1:8000
```

Start the server with `python -m app` rather than calling `uvicorn` directly.
On Windows, uvicorn picks an event loop that psycopg can't use in async mode,
and `app/__main__.py` works around that. On Linux it's an ordinary uvicorn run.

The API docs are at <http://127.0.0.1:8000/docs>.

To fetch a session by hand, bypassing the job queue (re-running is safe;
`--force` re-fetches a stored session):

```bash
.venv/Scripts/python -m scripts.ingest_session --year 2024 --round 14 --session race
```

### 3. Frontend

```bash
cd frontend
npm ci
cp .env.example .env.local    # NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
npm run build && npm start    # http://127.0.0.1:3000
```

`npm run dev` works too. If the page loads but never fetches anything, the dev
server's hot-reload socket is failing on your machine and the page never
hydrates. The production build above avoids that.

Use `127.0.0.1` rather than `localhost` in the API URL. Some browsers resolve
`localhost` to IPv6 first, and the backend listens on IPv4. The backend's
default `CORS_ORIGINS` allows both spellings of port 3000.

The season picker opens on the current season. Stored races from other seasons
only appear once you select that season.

## Tests and checks

```bash
# backend
cd backend
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m mypy app

# frontend
cd frontend
npm test                 # vitest
npm run typecheck && npm run lint
npm run test:e2e         # Playwright, against mocked API responses
```

The backend tests make no network calls. The storage tests (normalizer, job
store, SQL executor and others) run against the database in `backend/.env`,
each inside a transaction that is rolled back, so they leave nothing behind.
Without a `.env` they are skipped and the rest still run.

## API

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | Liveness. Never touches the database. |
| GET | `/health/db` | Checks Postgres. Don't poll it, or Neon never suspends. |
| GET | `/api/seasons/{year}/calendar` | Every round, marked `ingested`, `available` or `upcoming`. |
| GET | `/api/dashboard?season=` | Season summary. |
| GET | `/api/races/{year-round}` | Race header. |
| GET | `/api/races/{year-round}/stats` | Classification, pace, strategy, pit stops, race control. |
| POST | `/api/ingest` | Starts a session fetch and returns a job id (202). Rate limited. |
| GET | `/api/jobs/{id}` | Progress of a fetch or report job. |
| GET | `/api/standings/{year}/drivers` · `/constructors` | Championship standings. |
| POST | `/api/chat` | One question. Rate limited. |
| GET | `/api/races/{year-round}/report` · `/api/reports/{id}` | A stored report. |
| POST | `/api/races/{year-round}/report/generate` | Writes a report and returns a job id (202). Rate limited. |

The three endpoints that spend money are limited per client IP: chat 10 per
minute, ingest 20 per hour, reports 5 per hour. All three limits can be changed
in `.env`. Over the limit, the response is a 429 with `Retry-After`.

## Deployment

Deploy the backend first. The frontend needs the backend's URL at build time,
and the backend needs the frontend's domain for CORS.

### Backend container

`backend/Dockerfile` builds the image. At boot it runs `alembic upgrade head`
(set `RUN_MIGRATIONS=false` to skip that), then starts the server as a non-root
user. On the host:

- Set the variables from `backend/.env.example`, at least `DATABASE_URL`,
  `DATABASE_URL_READONLY`, `GROQ_API_KEY`, `GROQ_MODEL` and `CORS_ORIGINS`.
  The host usually sets `PORT` itself.
- Mount a **persistent volume at `/data/fastf1-cache`**. Without it, every
  restart forgets the FastF1 cache and each cold question downloads its session
  again.
- Point the health check at `/health`.
- Run **one instance, and don't let it scale to zero.** Ingestion jobs,
  conversations and rate-limit counts live in the process, and the post-race
  report loop only runs while the process is up.
- Set `CORS_ORIGINS` to the exact frontend domains, comma separated, for
  example `https://gridmind.vercel.app`. Wildcards are refused, so preview
  deployments need their own entries.

The image sets `FORWARDED_ALLOW_IPS` to private and internal address ranges,
which is where Railway, Render and Fly proxies connect from. That lets uvicorn
read the real client address from `X-Forwarded-For` for rate limiting. Don't
set it to `*`: uvicorn would then take the leftmost entry, which the client
writes, and anyone could get around the limits.

After changing dependencies in `pyproject.toml`, regenerate
`backend/requirements.lock` with the command at the top of the Dockerfile.

### Frontend on Vercel

- Set the project's root directory to `frontend`.
- Set `NEXT_PUBLIC_API_BASE_URL` to the backend's `https://` URL. Next.js
  writes this into the JavaScript at build time, so after changing it you must
  redeploy. A page served over `https` can't call an `http` backend.

If the site says it can't reach the backend, open the browser's network tab.
The failing request's URL shows which backend the build was given, and a CORS
error in the console means the backend's `CORS_ORIGINS` doesn't list the site's
domain.

## Known limits

- **Groq's free tier is small.** A question usually takes three LLM calls,
  and more when SQL has to be retried. At 8K tokens a minute that allows
  roughly three questions a minute across all visitors. Beyond that, chat returns a 429 and the page says when
  to retry.
- **Conversations are kept in memory**, so a restart or redeploy forgets them.
  The page then starts a new conversation without showing an error.
- **Finishing gaps aren't shown.** The classification's GAP column and the race
  page's winning MARGIN always show "—", because only lap times are stored, not
  race time.
- **One question fetches at most two sessions.** Questions that would need a
  whole season are refused with a suggestion instead, except standings.

## Data

Timing data comes from FastF1, which reads Formula 1's live timing service.
Standings come from jolpica-f1. GridMind is an unofficial project and is not
associated with Formula 1 or the FIA.
