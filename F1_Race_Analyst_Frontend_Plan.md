# GridMind — Frontend Implementation Plan

> **Revision 2 (2026-09-20).** The frontend is **supplied by the project owner**, so this
> document now serves two purposes: the original design brief, and — more importantly —
> the **contract the frontend must meet** to work with the on-demand-ingestion backend.
> Sections marked **[R2]** are new or rewritten. Section 6 (Loading Pit) changed the most:
> it is no longer a decorative spinner.

## 1. Goal

Build a polished F1-inspired website for the AI Race Analyst.

The website should combine:

1. A race dashboard.
2. Automated race reports.
3. A natural-language AI chatbot.
4. Driver/race/strategy statistics.
5. A distinctive F1-style loading experience called the **Loading Pit**.

The UI should feel like a modern motorsport data product rather than a generic AI chatbot.

---

## 2. What Changed in Revision 2 **[R2]**

Read this before anything else. Three backend decisions reshape the frontend:

**1. The database starts empty.** Nothing is pre-ingested. When a user asks about a
session the backend has never seen, it fetches that session from the F1 timing API first.
That takes roughly **30 seconds to 2 minutes**.

**2. The user never picks a race before asking.** There is no "select a season, then a
race, then ask" funnel. The agent reads the question, works out which race and session it
needs, and fetches it. Race browsing still exists, but it is a parallel way in, not a
prerequisite for chat.

**3. Conversations are not persisted.** The backend holds them in memory and they vanish
on restart or redeploy. The frontend must handle an unrecognised `conversation_id`
gracefully by starting fresh.

The practical consequence: **the Loading Pit is now load-bearing.** A user waiting 90
seconds at an undifferentiated spinner will assume the site is broken. The animation must
reflect real backend stages.

---

## 3. Recommended Stack

- Next.js
- TypeScript
- React
- Tailwind CSS
- shadcn/ui where useful
- Recharts or another lightweight chart library
- Framer Motion for animations
- Lucide icons
- Native Web Audio API for the Loading Pit sounds

The frontend communicates with the FastAPI backend through a small typed API client.

Do not put database credentials in the frontend.

**[R2]** The backend is **not** deployed on Vercel — it runs as a container elsewhere.
The frontend therefore talks to it cross-origin over HTTPS. Configure the backend base URL
through an environment variable (`NEXT_PUBLIC_API_BASE_URL`), and make sure the backend's
`CORS_ORIGINS` includes both the Vercel production domain and preview deployment domains.

---

## 4. Visual Direction

Design language:

- modern F1 broadcast/data interface
- dark background
- high-contrast typography
- motorsport-inspired panels
- dense but readable data
- subtle grid/track-inspired visual elements
- restrained use of racing-red accents
- smooth motion
- strong hierarchy
- responsive layout

Avoid:
- generic "AI SaaS" gradients everywhere
- excessive glassmorphism
- giant unnecessary animations
- clutter
- fake F1 team logos or copyrighted team branding unless explicitly licensed

Use generic motorsport visual language instead.

---

## 5. Main Pages

### `/`

Landing/dashboard.

Include:

- current/selected season
- latest race
- race countdown/status where data exists
- latest podium
- latest report
- quick statistics
- "Ask the Race Analyst" entry point
- recent races

Hero section:

```text
GRIDMIND

Ask questions.
Explore the data.
Understand the race.

[ Ask the Analyst ]
[ View Latest Race ]
```

**[R2]** The homepage must render correctly when the database is empty — on a fresh
deployment there is no "latest race" with results yet. Fall back to calendar data from
`/api/seasons/{year}/calendar`, which needs no ingestion, and present an empty state that
invites a question rather than showing broken panels.

---

### `/races`

Race listing.

Features:

- season selector
- race calendar
- race status
- circuit
- date
- winner
- quick result

Each race should link to `/races/[id]`.

**[R2]** Distinguish three states per race in the calendar:

```text
[ Ingested ]     full data available, opens instantly
[ Available ]    race has happened, data not yet fetched — opening triggers ingestion
[ Upcoming ]     race has not happened
```

Do not hide un-ingested races. Make the cost of opening them visible instead.

---

### `/races/[id]`

Race detail page.

Sections:

1. Race header
2. Podium
3. Race classification
4. Position changes
5. Lap pace
6. Tyre strategy
7. Pit stops
8. Key events
9. AI-generated race report
10. Ask about this race

The page should allow users to jump between sections.

**[R2]** If the race is not yet ingested, opening this page triggers an ingestion job.
Show the Loading Pit against the real job progress, then render. If the user navigates
away, the job continues on the backend — returning later should find it complete.

**[R2]** Historic races have **no report until someone asks for one**. Section 9 should
show a "Generate race report" action rather than an empty panel. Reports for recent races
are generated automatically and will already be there.

---

### `/reports/[id]`

Full report page.

Display:

- report title
- race information
- generated timestamp
- summary
- race story
- driver highlights
- strategy analysis
- key statistics
- notable events
- conclusions/takeaways

Include a "Ask about this race" button.

**[R2]** Report generation is the most expensive operation in the system. Once generated,
a report is stored permanently — never offer a "regenerate" button in the normal UI.

---

### `/chat`

Main AI analyst interface.

Layout:

```text
+----------------------------------------------------+
| GRIDMIND                              [Season]     |
+----------------------+-----------------------------+
| Conversation         |                             |
|                      |      AI RESPONSE            |
| Recent questions     |                             |
|                      |      tables/charts          |
|                      |                             |
|                      |                             |
+----------------------+-----------------------------+
| Ask anything about F1...                    [Send] |
+----------------------------------------------------+
```

The chatbot should support:

- normal English
- suggested prompts
- tables
- numeric results
- comparisons
- citations/references to the underlying race/data where the backend provides them

Example prompts:

```text
Who gained the most positions at the last race?

Compare the race pace of Verstappen and Norris.

Which drivers used a one-stop strategy?

What was Norris's Q3 time at Monza?

Who has the most points this season?
```

**[R2]** Because conversations live in memory only, the sidebar's "recent questions" is
per-session. Do not present it as durable history, and do not promise the user their
conversation will be there tomorrow.

---

## 6. Chat Response Rendering

Do not display every answer as a wall of text.

If the backend returns structured data, render it appropriately.

### Response shape **[R2]**

```json
{
  "answer": "Norris gained the most positions...",
  "data": [
    {
      "driver": "Lando Norris",
      "grid": 8,
      "finish": 3,
      "positions_gained": 5
    }
  ],
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

Render `answer` plus `data` as a concise answer, a table, and an optional chart. The
backend decides the data shape; the frontend decides how to visualize it.

**[R2] Three fields need explicit frontend handling:**

**`resolved_entities`** — show the user what the agent decided they asked about. When
someone asks "who won at Monza?" and the agent inferred 2025, that inference must be
visible, ideally as a small chip above the answer:

```text
2025 · Italian Grand Prix · Race
```

This is how a user catches a wrong inference instead of trusting a confidently wrong answer.

**`ingestion.job_id`** — when present, the answer is **not ready yet**. The backend
returns promptly with a job id rather than holding the connection open. The frontend
polls `/api/jobs/{job_id}` or subscribes to `/api/jobs/{job_id}/stream`, drives the
Loading Pit from it, and re-requests the answer on completion.

**`needs_clarification`** — the agent could not identify the race. Render
`clarifying_question` as a normal assistant turn and wait. Do not show the Loading Pit,
and do not render an empty table.

---

## 7. Loading Pit **[R2 — substantially rewritten]**

This is the signature feature, and revision 2 gives it a real job.

Create a reusable overlay called `LoadingPit`, shown when the site is:

- waiting for an ingestion job
- loading a race
- generating a report
- waiting for the AI analyst

### Visual

Display motorsport-inspired start lights.

```text
        LOADING PIT

       o  o  o  o  o

      FETCHING TIMING DATA
```

Lights illuminate sequentially, then all hold, then clear as content appears.

Do not copy broadcast graphics pixel-for-pixel. Make it an original motorsport-inspired
interpretation.

### The lights map to backend stages, not to elapsed time **[R2]**

This is the key change. The backend's `ingestion_jobs` row exposes a `stage` field. Bind
each light to a stage:

```text
Light 1   resolving     "Resolving the session"
Light 2   fetching      "Fetching timing data"
Light 3   storing       "Storing results and laps"
Light 4   verifying     "Running analytics"
Light 5   answering     "Writing your answer"
```

Rules:

- **A cold request genuinely takes 30s–2min.** Lights advance as stages complete. Light 2
  (fetching) is the long one; it must be able to hold for a minute without looking stuck.
  Give it a subtle secondary motion or an elapsed counter so the user can tell the
  difference between "working" and "frozen".
- **A warm request skips ahead.** If the session is cached, the backend never creates a
  job. Jump to the last light and finish quickly.
- **Never fake progress.** Do not animate lights on a timer when no stage has completed.
  A user who sees five lights fill and then waits another 40 seconds will not trust the
  interface again.
- **Never artificially delay a fast response** to show the animation.
- **Surface failure.** A job can fail or time out. The Loading Pit needs an error state
  that says what failed, not an animation that runs forever.
- **Survive navigation.** Jobs run on the backend. If the user leaves and returns, resume
  from current job state rather than restarting.

### States

```text
loading
success
error
```

### API

```tsx
<LoadingPit
  active={loading}
  stage={job?.stage}            // [R2] drives which light is lit
  message="Fetching timing data..."
  elapsedSeconds={elapsed}      // [R2] for long fetch stages
  error={job?.error_message}    // [R2]
  soundEnabled={soundEnabled}
  onSkipAnimation={...}
/>
```

Messages should track the real stage:

```text
Resolving the session...
Fetching timing data...
Storing results and laps...
Running analytics...
Preparing your answer...
```

---

## 8. Loading Pit Audio

Use the Web Audio API.

Requirements:

- short beep for each light
- slightly stronger final sequence
- sound starts only after user interaction when browser autoplay rules require it
- provide a mute/unmute control
- remember the user's mute preference locally

Do not ship copyrighted F1 broadcast audio. Generate simple synthesized tones. Audio
should be subtle and short.

Provide:

```text
Sound: ON/OFF
```

**[R2]** Because stages can now take a minute, beeps are tied to **stage transitions**,
not to a fixed animation timeline. There should be no repeating or looping sound during a
long fetch — five discrete beeps across ninety seconds, not a drone.

Accessibility:
- respect `prefers-reduced-motion`
- provide a way to skip the animation
- do not make audio required to understand loading status

---

## 9. Dashboard Components

Create reusable components:

```text
RaceCard
DriverCard
PodiumCard
StatCard
RaceTable
DriverComparison
TyreStrategyChart
LapPaceChart
PositionChangeChart
PitStopTable
RaceReport
ChatMessage
ChatInput
SuggestedQuestion
LoadingPit
ResolvedEntitiesChip      [R2]
ClarifyingQuestion        [R2]
IngestionStatusBadge      [R2]
GenerateReportButton      [R2]
Header
Sidebar
SeasonSelector
```

Keep components small and composable.

---

## 10. Race Data Visualizations

Use charts where they communicate something useful.

### Lap Pace
Line chart:

```text
Lap time
  |
  |     /\      /\
  | /\ /  \ /\ /  \
  +------------------- Lap
```

### Position Change

Horizontal/vertical bar visualization.

### Tyre Strategy

Timeline:

```text
Laps
0       20       40       60

MEDIUM  |---------|
HARD              |---------------|
```

### Driver Comparison

Side-by-side statistics:

```text
                 Driver A   Driver B
Finish              2          4
Grid                5          3
Fastest Lap       1:32       1:33
Pit Stops           2          1
```

Do not create a chart when a simple table communicates the data better.

**[R2]** No telemetry charts. The backend does not ingest car telemetry channels
(speed/throttle/brake/gear traces), so throttle traces and similar are out of scope for v1.

---

## 11. Responsive Design

Desktop:
- sidebar/navigation
- large charts
- multi-column dashboard

Tablet:
- collapsible sidebar
- two-column cards

Mobile:
- bottom navigation or compact header
- single-column cards
- horizontally scrollable tables
- chat input fixed near bottom
- charts remain readable

The Loading Pit must work well on mobile.

---

## 12. API Client **[R2]**

```text
frontend/
└── lib/
    └── api/
        ├── client.ts
        ├── races.ts
        ├── reports.ts
        ├── standings.ts     [R2]
        ├── jobs.ts          [R2]
        └── chat.ts
```

Use typed response models.

```ts
getCalendar(year)                    // [R2] no ingestion required
getRaces()
getRace(id)
getRaceStats(id)
getReport(id)
generateReport(id)
getDriverStandings(year)             // [R2] via standings adapter
getConstructorStandings(year)        // [R2]
sendChatMessage(message, conversationId)
getJob(jobId)                        // [R2] poll ingestion progress
streamJob(jobId)                     // [R2] SSE progress
```

Handle:

- loading
- timeout
- network errors
- API errors
- empty results
- **rate-limit responses (HTTP 429)** **[R2]**
- **unrecognised conversation id** **[R2]**

**[R2] Timeouts need care.** The default fetch timeout must not be shorter than a cold
ingest. Better: the chat call returns fast with a job id, and only the job poll is
long-lived. Do not set a blanket 30-second client timeout, or every cold question will
appear to fail.

---

## 13. Chat UX

The chatbot should feel like a race engineer/analyst rather than a generic assistant.

When empty:

```text
Ask the Race Analyst

I can help you explore race results, driver performance,
strategy, tyres, pit stops and season statistics.

Try asking:

"Who had the best race pace at Monza?"

"Compare Norris and Leclerc."

"Who has the most points this season?"
```

When answering:

- show the Loading Pit, bound to real job stages, while waiting
- show the resolved entities chip so the user can see which race was inferred
- render structured tables/charts
- show data references where available
- preserve conversation for the session

**[R2] Set expectations on first use.** A first-time visitor asking about an obscure 2019
session will wait over a minute. One line of copy near the input — something like *"First
question about a session takes a moment while we fetch the timing data"* — converts a
suspected bug into understood behaviour.

**[R2] Suggested prompts should be honest about cost.** Prefer prompts about recent races,
which are more likely to be cached.

---

## 14. Error States

Create useful error states.

```text
THE PIT CREW HIT A PROBLEM

We couldn't retrieve the race data.

[Try Again]
```

For chatbot failures:

```text
I couldn't get a reliable answer from the race data.

Try rephrasing the question or asking about a specific race.
```

Do not expose raw stack traces to users.

**[R2] These failures are genuinely different and need distinct messages:**

| Condition | What to say |
|---|---|
| Ingestion job failed | The timing data for that session could not be retrieved. Offer retry. |
| Ingestion timed out | Taking longer than expected — the job may still finish. Offer to check back. |
| No data matched the query | We have the session, but nothing matched. Suggest rephrasing. |
| Ambiguous question | Render `clarifying_question` as a normal assistant turn. Not an error. |
| Too many sessions required | The question is too broad. Suggest narrowing to one race. |
| Rate limited (429) | Too many requests right now. Give a concrete retry hint. |
| LLM rate limit / quota | The analyst is busy. Try again shortly. Do not blame the user. |
| Unknown conversation id | Start a fresh conversation silently. Not a visible error. |

Collapsing all of these into "something went wrong" makes the product feel broken when it
is often working correctly.

---

## 15. Accessibility

Implement:

- semantic HTML
- keyboard navigation
- visible focus states
- accessible labels
- sufficient contrast
- reduced motion support
- audio controls
- no information conveyed by color alone

**[R2]** The Loading Pit must announce progress to screen readers via an
`aria-live="polite"` region, announcing each stage transition as text ("Fetching timing
data"). With waits over a minute, a silent region is an accessibility failure, not a
nicety. Announce the elapsed state periodically rather than only at start and finish.

---

## 16. Performance

Optimize:

- lazy-load heavy charts
- avoid unnecessary animation rerenders
- cache race data client-side where appropriate
- debounce chat input if needed
- avoid loading all race data at once
- paginate large tables

Do not send huge datasets to the browser if the backend can aggregate them first.

**[R2]** Poll job status at a sensible interval — roughly 1–2 seconds — or prefer the SSE
stream. Do not poll aggressively; the backend is a single modest container, and this is
one of the few places the frontend can create real load.

---

## 17. State Management

Do not introduce a large state-management library unless needed.

Start with:

- React state
- React Context for small global settings
- URL query parameters for filters
- a lightweight server-state solution only if API caching becomes complex

Persist only appropriate preferences locally:

```text
sound enabled/disabled
theme preference
selected season
```

**[R2]** Active ingestion job ids are worth keeping in client state (or the URL) so a
page refresh mid-ingest can reattach to the running job rather than starting over.

**[R2]** Do not attempt to persist conversations to localStorage as a workaround for the
backend's in-memory store. The backend will not recognise a restored conversation id, and
the restored context would be a lie — the agent has no memory of it.

---

## 18. Design Details

Add small details that make the interface feel intentional:

- animated lap/sector indicators
- subtle scanline/grid motifs
- race flag/circuit metadata
- compact telemetry-style numbers
- smooth table row transitions
- hover states
- animated counters for important statistics
- status indicators

Keep animation subtle outside the Loading Pit.

---

## 19. Frontend Implementation Order

1. Initialize Next.js/TypeScript project.
2. Create global design system.
3. Create app shell/navigation.
4. Implement API client and mock data.
5. Build dashboard.
6. Build race list.
7. Build race detail page.
8. Build report page.
9. Build chatbot.
10. Build charts.
11. Implement Loading Pit.
12. Implement synthesized audio.
13. Connect real backend APIs.
14. Wire ingestion job polling into the Loading Pit. **[R2]**
15. Add the full matrix of loading/error/empty states from section 14. **[R2]**
16. Add responsive layouts.
17. Add accessibility, including the Loading Pit live region. **[R2]**
18. Optimize performance.
19. Run production build and fix all errors.
20. Deploy to Vercel with `NEXT_PUBLIC_API_BASE_URL` pointing at the container backend. **[R2]**

Build with mock data first so frontend work is not blocked by backend development.

**[R2]** Mock data must include a **slow cold path**, not just instant success. A frontend
developed only against instant mocks will have an untested Loading Pit, which is the one
component most exposed by real backend behaviour.

---

## 20. Definition of Done

The frontend is complete when:

- Users can browse races.
- Users can view detailed race information.
- Users can read generated race reports.
- Users can request a report for a historic race. **[R2]**
- Users can ask the AI questions in normal English without selecting a race first. **[R2]**
- Structured chatbot results become tables/charts.
- Resolved entities are visible, so a wrong inference is catchable. **[R2]**
- Clarifying questions render as conversation, not as errors. **[R2]**
- Loading operations use the Loading Pit.
- Loading Pit lights advance on real backend stages, not on a timer. **[R2]**
- A 90-second cold ingest reads as working, not frozen. **[R2]**
- Ingestion failures and timeouts have distinct, useful error states. **[R2]**
- A page refresh mid-ingest reattaches to the running job. **[R2]**
- Loading Pit has sequential start-light animation.
- Loading Pit has synthesized beeps tied to stage transitions. **[R2]**
- Audio can be muted.
- Reduced-motion users can skip/reduce animation.
- Screen readers are told what stage loading is at. **[R2]**
- The site works on desktop and mobile.
- Rate-limit (429) responses are handled gracefully. **[R2]**
- The site renders correctly against an empty database. **[R2]**
- API errors have good UX.
- No secrets are exposed in the browser.
- Production build succeeds.
