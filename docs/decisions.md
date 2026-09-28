# Design decisions

Short records of the choices that shape ClaimsWatch, and why we made them.

## 1. A statistical baseline, not a machine-learning model

**Decision.** Score each window's error counts (one per log template, see 3)
with a modified z-score against a rolling median and MAD.

**Why.** The signal is a handful of counts per 10-second bucket. A statistical baseline
needs about two minutes of history instead of a labelled training set, costs
microseconds per bucket, and every alert can be explained in one sentence: the
error count was *x*, normal is *y*, that is *z* robust standard deviations
away. For an on-call engineer, and for a regulated healthcare environment,
being able to say exactly why an alert fired matters more than squeezing out a
few points of accuracy.

**Trade-off.** It will not learn weekly seasonality or correlations between
services. The detector interface (`observe`, `close_bucket`) would let a
seasonal model replace the baseline without touching the rest of the system.

## 2. Median and MAD instead of mean and standard deviation

**Decision.** Use the modified z-score `0.6745 * (rate - median) / MAD`
(Iglewicz and Hoaglin, 1993) with WARNING at 3.5, the cut-off they recommend.

**Why.** Mean and standard deviation are dragged by the outliers we are trying
to find: one past spike inflates the standard deviation and hides the next
one. The median and MAD barely move when a few samples are extreme.

**Guards.** MAD is floored (`MAD_FLOOR`, default 0.002) so a perfectly steady
service cannot turn a tiny wobble into an enormous score, and no alert fires
unless the window holds at least `MIN_ERRORS` errors and `MIN_TOTAL` lines.
HIGH (5) and CRITICAL (8) are our own escalation points, not from the paper.

## 3. Count errors per log template (Drain3), not in one global total

**Decision.** Mine templates from masked lines with Drain3 and score each
template's error count per window against its own median and MAD, reusing
the same `RobustBaseline`. Incidents are keyed by detector and template.

**Why.** A single global error rate dilutes a new failure in background
noise: 3 timeouts a second on a 40-line/s stream moved the global rate by
only a few robust deviations, and took two buckets to alert. As a template
of its own with a history of zeros it is unmistakable in the first bucket.
Templates also give each alert a precise "what" (the template text) and
parameters (the attacking IP) without hand-written regexes per message.

**Guards.** Counts, unlike rates, have a natural noise level: a Poisson
count with median *m* scatters by about sqrt(*m*). Consecutive windows share
five of six buckets, so the MAD measured over them understates that scatter,
and without a floor ordinary noise in busy templates raised 6 false alarms in
the replay. MAD is therefore floored at `max(TEMPLATE_MAD_FLOOR,
0.6745 * sqrt(median))`. The template cache and the per-template baselines
are capped at `MAX_TEMPLATES`, least recently seen first out.

**Trade-off.** Drain3 needs lines of a stable shape; a message whose token
count varies (free text) can split into several templates, each with a
smaller count. The global rate is still computed and charted as a control.

## 4. Incidents, not per-bucket alerts

**Decision.** The first anomalous bucket opens an incident; later anomalous
buckets update or escalate it; it resolves after `RESOLVE_AFTER_BUCKETS`
consecutive normal buckets. The baseline stops learning while an incident is
open.

**Why.** A 45-second outage would otherwise page someone five times. One
incident per problem, carrying its peak severity and a summary of what broke,
is what an on-call engineer can act on. Freezing the baseline means a long
outage never becomes the new normal. Only open, escalate and resolve go to
AWS; routine updates only refresh the dashboard.

## 5. Mask at the parser

**Decision.** Mask member IDs, names, dates of birth, e-mails, SSNs and phone
numbers in the whole line before any field is extracted.

**Why.** HIPAA's minimum-necessary standard. If masking happens at the edge,
no later component (database, dashboard, SNS, CloudWatch) can leak PHI by
accident. Masking also normalises messages, so "lookup failed for M1234567"
and "lookup failed for M7654321" are counted as one error.

## 6. SQLite for alert history

**Decision.** Store alerts with the standard-library `sqlite3` module; keep
stats points in memory.

**Why.** Alerts must survive a restart, but this is a sidecar with one writer,
and SQLite needs no server, no credentials and no extra container. Stats are
cheap to regenerate and only feed the chart. Moving to PostgreSQL or DynamoDB
would only touch `alerts/store.py`.

## 7. moto instead of a real AWS account

**Decision.** Run the real boto3 code against the moto emulator locally, via
`AWS_ENDPOINT_URL`.

**Why.** We had no AWS account for the event. moto implements the SNS, SQS and
CloudWatch Logs APIs closely enough that the same code, unchanged, publishes to
real AWS once the endpoint override is removed and credentials are provided.
Tests use moto's in-process `mock_aws`; the demo uses `moto_server`.

## 8. Delivery in the background

**Decision.** Alerts go onto an asyncio queue; a single worker makes the boto3
calls in a thread and records per-channel results on the alert.

**Why.** Detection must never wait on the network. If AWS is slow or down, the
card shows `failed` with the error and the dashboard keeps updating.

## 9. Polling the log file instead of inotify

**Decision.** The tailer polls every 250 ms and compares size and inode.

**Why.** It behaves the same on Linux, macOS and Docker bind mounts, and makes
truncation and rotation handling explicit and testable. The cost is at most a
quarter-second of added latency, which is small next to 10-second buckets.
