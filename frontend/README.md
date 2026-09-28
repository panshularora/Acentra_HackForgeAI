# ClaimsWatch dashboard

Real-time view of the ClaimsWatch detector: the error rate against its learned
baseline, and a feed of incidents as the backend opens, updates and resolves
them.

React 19, TypeScript (strict), Vite, Recharts, and React Three Fiber (three.js)
with Drei for the 3D detector view. Plain CSS driven by the tokens in
`src/theme.ts`.

## What is on screen

- **Status hero**: one sentence answering "is anything wrong?" (all clear,
  learning, open incident, monitoring degraded, or backend unreachable), the
  four key numbers, and the 3D detector view.
- **Detector view** (`components/scene/`): each dot is a log line flowing into
  the detector core, error lines in red, at the live lines-per-second and error
  share from the latest bucket. The dashed ring is the edge of normal and the
  solid ring is the current error rate on the same scale. The core takes the
  severity colour and beats faster while an incident is open, pulses once when
  one opens or escalates, and dims and stalls while `/api/health` reports
  `degraded`. It is lazy-loaded, caps the pixel ratio at 1.75, stops rendering
  when the tab is hidden or the canvas is off screen, freezes motion under
  `prefers-reduced-motion`, and falls back to a static SVG with the same
  meaning when WebGL is unavailable or the context is lost.
- **Error-rate chart**, **incident feed** (open incidents show why they fired,
  resolved ones fold that away), **alert delivery** (SNS / CloudWatch target
  and whether the last alert got there) and **demo faults** (copyable commands
  for the three faults the live detector catches; the backend has no API to
  inject faults).

## Run

Requires Node 22+. Start the backend on `:8000` first (see the repository
README), then:

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api and /ws to :8000
```

Point the dev proxy elsewhere with `BACKEND_URL=http://host:port npm run dev`.

## Checks

```bash
npm run lint       # ESLint, zero warnings allowed
npm run typecheck  # tsc in strict mode
npm test           # Vitest + React Testing Library
npm run build      # production bundle in dist/
```

## How it stays live

`src/hooks/useAlertStream.ts` opens one WebSocket to `/ws`. Each message is
either a `stats` bucket (every 10 seconds) or a full `alert` object, and a pure
reducer (`alertStreamReducer.ts`) merges it into state: stats are de-duplicated
by timestamp and trimmed to the last 10 minutes, alerts are upserted by id and
an older copy never overwrites a newer one.

While the socket is live the hook also re-reads `/api/health` every 5 seconds.
Newer backends answer `status: "degraded"` with `ingest_error` while log
ingest is failing and retrying; the dashboard then says "Monitoring degraded,
retrying" with the error, which is worded differently from a lost connection.
Backends without these fields read as healthy.

If the socket drops, the status bar shows "Reconnecting" and the hook retries
with exponential backoff (1s, 2s, 4s, 8s, capped at 15s, with jitter). Every
successful (re)connect backfills from `/api/stats` and `/api/alerts`, so a
page refresh or a backend restart never leaves a gap in the chart or the feed.

## Layout of `src/`

| Path                          | Purpose                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------ |
| `types.ts`                    | Wire types for REST and WebSocket payloads, matching the backend contract      |
| `theme.ts`                    | Every colour, font, size and spacing token; applied as CSS variables           |
| `api/client.ts`               | Fetch helpers for `/api/health`, `/api/stats`, `/api/alerts` and acknowledge   |
| `hooks/useAlertStream.ts`     | WebSocket lifecycle: reconnect with backoff, backfill on connect               |
| `hooks/alertStreamReducer.ts` | Pure state rules: merge stats, upsert alerts, route messages                   |
| `lib/`                        | Pure helpers: formatting, baseline progress, chart axis steps                  |
| `lib/scene.ts`                | Pure mapping from live data to the headline state and the 3D view's look       |
| `lib/health.ts`               | Reads `status` / `ingest_error` from `/api/health` into ok / degraded          |
| `components/`                 | Status bar, hero, summary strip, chart, alert feed and cards, delivery, faults |
| `components/scene/`           | 3D detector view (lazy R3F canvas), particle simulation, static SVG fallback   |

## Docker

`Dockerfile` builds the bundle and serves it with nginx; `nginx.conf` proxies
`/api` and `/ws` to a service named `backend` on port 8000.
