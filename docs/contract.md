# Backend <-> frontend contract

The source of truth for both tracks. Version 1 is the original contract;
version 2 adds template-aware detection. Every v2 field is additive, so a
client built against v1 keeps working. The backend's `to_dict` methods in
`backend/app/models.py` produce exactly these shapes; `docs/architecture.md`
shows full examples.

## Version 1

Project working name: **ClaimsWatch** (real-time log anomaly detection for Medicaid claims services). Name lives in one place per side (backend config APP_NAME, frontend theme/const) so it can be renamed.

Backend: FastAPI on :8000. Frontend: Vite on :5173 with dev proxy `/api` and `/ws` -> http://localhost:8000 (ws: true).

### REST
- GET /api/health -> {"status":"ok","app":"ClaimsWatch","log_path":str,"tailer_offset":int,"aws":{"sns_topic_arn":str|null,"cloudwatch_log_group":str|null,"endpoint":str|null}}
- GET /api/stats?minutes=10 -> {"points":[StatsPoint,...]} oldest first
- GET /api/alerts?limit=50 -> {"alerts":[Alert,...]} newest first (by opened_at)
- POST /api/alerts/{id}/ack -> Alert (sets acknowledged=true)  [small extra]

### WebSocket /ws  (server -> client JSON messages; client sends nothing required)
Every message: {"type": "stats" | "alert", "data": ...}
- type "stats": sent once per closed 10-second bucket, data = StatsPoint
- type "alert": sent when an incident opens, updates, resolves, gets acked, or its AWS delivery status changes; data = full Alert (client upserts by id)

### StatsPoint
{
  "ts": "2026-09-28T13:05:10Z",      // bucket end, ISO-8601 UTC
  "total": 412,                       // log lines in the sliding window (60s)
  "errors": 9,                        // error lines in the window
  "error_rate": 0.0218,               // errors/total over the window, 0..1
  "baseline_median": 0.019,           // null until baseline is warm
  "band_upper": 0.031,                // median + 3.5*MAD/0.6745 (edge of "normal"); null until warm
  "score": 0.8,                       // modified z-score, null until warm
  "severity": null | "WARNING" | "HIGH" | "CRITICAL"
}

### Alert
{
  "id": "a3f9c2e1",
  "status": "open" | "resolved",
  "severity": "WARNING" | "HIGH" | "CRITICAL",   // peak severity so far
  "score": 9.4,                                   // peak score
  "error_rate": 0.31, "baseline_median": 0.02,    // at peak
  "opened_at": iso, "updated_at": iso, "resolved_at": iso|null,
  "summary": "94% of errors come from claim-adjudication: DB connection timeout",
  "top_contributors": {
    "services":   [{"value":"claim-adjudication","count":212,"share":0.94}],
    "messages":   [{"value":"DB connection timeout for member <MEMBER_ID>","count":200,"share":0.89}],
    "source_ips": [{"value":"10.4.2.17","count":310,"share":0.97}]
  },
  "sample_lines": ["2026-09-28T13:05:03Z ERROR claim-adjudication ... <MEMBER_ID> ..."],  // masked, max 5
  "acknowledged": false,
  "delivery": {
    "sns":        {"status":"pending"|"sent"|"failed"|"disabled","message_id":str|null,"error":str|null},
    "cloudwatch": {"status":"pending"|"sent"|"failed"|"disabled","error":str|null}
  }
}

Severity thresholds (modified z-score = 0.6745*(rate-median)/MAD, Iglewicz & Hoaglin 1993):
WARNING >= 3.5 (the published outlier cut-off), HIGH >= 5, CRITICAL >= 8 (our choices, documented as such).

Visual system (frontend): charcoal background (not pure black, e.g. #15171a / surface #1d2024 / border #2a2e33), one neutral text color + one muted secondary, colour ONLY for severity: WARNING amber #f2b233, HIGH orange #f07a2e, CRITICAL red #e5484d; ok/connected green used only for the tiny status dot. Fonts: Inter for UI, JetBrains Mono for log lines/numbers. All in frontend/src/theme.ts; SEVERITY_COLOR keys exactly WARNING/HIGH/CRITICAL. No gradients, glassmorphism, emoji, stock illustrations, or decorative particles. Only animation: new alert card slides in + one pulse in its severity colour; respect prefers-reduced-motion.

## Version 2: template-aware detection (additive to version 1)

All new fields are ADDITIVE. Every existing field keeps its name, type and meaning,
so the current dashboard keeps working if the new fields are missing or null.

### Detectors
Alert.detector is one of:
- "error_spike": per-template error count over the 60s window deviates from that
  template's own median + MAD baseline (modified z-score, same floor, same
  min-errors guard, same WARNING 3.5 / HIGH 5 / CRITICAL 8 config thresholds).
  Replaces the single global error count as the alerting signal.
- "silence": a template with a steady cadence (regular heartbeat-like gaps) has not
  been seen for far longer than its typical gap.
- "new_pattern": an ERROR/WARN template never seen before appears more than once
  after the warm-up period.
- "flow_break": the hand-declared pair "claim validated" followed by
  "claim adjudicated" stops completing (validated without adjudicated within the
  expected delay, at an abnormal rate).

The global error rate stays in StatsPoint for the chart and as the benchmark control.

### StatsPoint additions
"learning": {"state": "learning" | "ready", "buckets_seen": int, "buckets_needed": int,
             "templates": int}   // templates = distinct Drain3 templates seen so far

### Alert additions (nullable)
"detector": "error_spike" | "silence" | "new_pattern" | "flow_break",
"template": {"id": str, "text": "DB connection timeout for member <*>", "service": str | null} | null,
"baseline_band": {"median": float, "upper": float, "unit": str} | null,
     // unit examples: "errors/60s", "seconds between lines", "incomplete flows/60s"
"observed": float | null,         // the value that broke the band, same unit, at peak
"first_bad_line": str | null,     // masked raw line that first crossed the band
"params": [{"name": str, "value": str, "count": int, "share": float}]
     // top values of Drain3-extracted parameters, e.g. {"name":"source_ip","value":"10.4.2.17",...}

summary stays a single human sentence and still names the IP for credential stuffing.

### Health additions (/api/health)
"status": "ok" | "degraded"   // degraded when the pipeline stopped or the log cannot be read
"ingest_error": str|null      // why the last read of the log failed; null while reading works
GET /health returns 200 {"status":"ok"} or 503 {"status":"degraded"} on the same condition.
"detector": {"window_seconds": int, "bucket_seconds": int, "baseline_min_buckets": int,
             "detectors": ["error_spike","silence","new_pattern","flow_break"]}
"learning": same object as in StatsPoint.

### SNS
One message on open, escalate and resolve, with an event field "opened" | "escalated" | "resolved".
