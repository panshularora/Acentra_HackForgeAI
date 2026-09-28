# ClaimsWatch dashboard

Real-time view of the ClaimsWatch detector: the error rate against its learned
baseline, and a feed of incidents as the backend opens, updates and resolves
them.

React 19, TypeScript (strict), Vite, Recharts. Plain CSS driven by the tokens
in `src/theme.ts`.

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

If the socket drops, the status bar shows "Reconnecting" and the hook retries
with exponential backoff (1s, 2s, 4s, 8s, capped at 15s, with jitter). Every
successful (re)connect backfills from `/api/stats` and `/api/alerts`, so a
page refresh or a backend restart never leaves a gap in the chart or the feed.

## Layout of `src/`

| Path | Purpose |
| --- | --- |
| `types.ts` | Wire types for REST and WebSocket payloads, matching the backend contract |
| `theme.ts` | Every colour, font, size and spacing token; applied as CSS variables |
| `api/client.ts` | Fetch helpers for `/api/health`, `/api/stats`, `/api/alerts` and acknowledge |
| `hooks/useAlertStream.ts` | WebSocket lifecycle: reconnect with backoff, backfill on connect |
| `hooks/alertStreamReducer.ts` | Pure state rules: merge stats, upsert alerts, route messages |
| `lib/` | Pure helpers: formatting, baseline progress, chart axis steps |
| `components/` | Status bar, summary strip, error-rate chart, alert feed and cards |

## Docker

`Dockerfile` builds the bundle and serves it with nginx; `nginx.conf` proxies
`/api` and `/ws` to a service named `backend` on port 8000.
