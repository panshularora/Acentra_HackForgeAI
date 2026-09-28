# Demo script (3 minutes)

A rehearsed walk-through: calm system, database outage, credential stuffing,
proof that alerts reach AWS with patient data masked, and the replay numbers.

## Before the demo (not on the clock)

Start everything at least **3 minutes early** so the baseline is warm (it
needs one full 60 s window plus six 10 s samples, about two minutes).

```bash
docker compose up --build          # moto, backend, log generator, dashboard
```

or, without Docker, in four terminals:

```bash
make moto                                             # 1. AWS emulator on :5000
AWS_ENDPOINT_URL=http://localhost:5000 make dev       # 2. backend on :8000
make loggen                                           # 3. normal traffic
cd frontend && npm install && npm run dev             # 4. dashboard on :5173
```

Open a spare terminal for the incident commands and another running
`make sns-tail` (shows alerts as SNS delivers them). With Docker, prefix the
incident commands with `docker compose exec loggen` (see the README).

Check: the dashboard's status dot is green, the chart shows a flat line inside
the shaded band, and the alert feed is empty.

## 1. The problem (0:00 - 0:20)

Show the calm dashboard.

> "This is a Medicaid claims platform: eligibility checks, claim
> adjudication, member login, provider directory, payments. About 2% of
> requests always fail, and that's normal. The shaded band is what our system
> has learned 'normal' looks like. When something really breaks, the on-call
> engineer should know what broke and where within seconds, before a member
> is turned away at the pharmacy."

## 2. Database outage (0:20 - 1:20)

```bash
make incident-db        # claim-adjudication loses its database for 45 s
```

While it runs:

> "Claim adjudication just lost its database. Watch the error-rate line."

Within 10 to 20 seconds the line leaves the band and an alert slides in,
at WARNING or HIGH, escalating to CRITICAL within about 30 seconds as the
outage fills the window.

Point at the card:

> "One alert, not one every ten seconds. The summary says what broke and
> where: most errors come from claim-adjudication, and the message is 'DB
> connection timeout'. It was opened within two buckets of the outage
> starting. The score is a modified z-score: how many robust standard
> deviations above normal we are."

Point at the timestamps (opened_at versus when you ran the command).

## 3. Credential stuffing (1:20 - 2:05)

```bash
make incident-auth      # one IP hammers member-auth with stolen passwords
```

> "Different failure: someone is trying stolen passwords against member
> login."

An alert naming the source IP appears within about 10 seconds and reaches
CRITICAL within about 20:

> "It names the attacker: '… failed logins from 10.4.2.17 in the last 60
> seconds'. The security team can block that IP straight from the alert."

## 4. Trust (2:05 - 2:35)

Expand a sample log line on the alert card.

> "Every line is masked before it is stored or sent anywhere. Member IDs,
> names, e-mails, SSNs and phone numbers become tags like `<MEMBER_ID>`.
> That's HIPAA's minimum-necessary rule: the engineer needs to know that
> lookups fail, not whose."

Switch to the `make sns-tail` terminal.

> "Each alert is published to Amazon SNS and CloudWatch Logs. This terminal
> is a subscriber reading the alert back; the message id matches the one on
> the card. This is real boto3 code running against a local AWS emulator
> because we don't have an AWS account here. Pointing it at real AWS is one
> environment variable."

## 5. Proof (2:35 - 2:55)

```bash
make replay
```

> "We don't just demo it once. The replay test generates twenty minutes of
> traffic with both incidents at known times and runs it through the same
> detector. Both incidents are caught within two ten-second buckets, with zero
> false alarms during the normal traffic. It runs in our test suite."

## Likely questions

**Why not just use CloudWatch anomaly detection?**
> "ClaimsWatch runs next to the service, so it masks patient data before
> anything leaves the machine, and it turns a spike into one incident that
> says what broke and where, not just that a metric moved. It's a layer in
> front of CloudWatch, not a replacement: our alerts land in CloudWatch Logs
> and SNS, where the existing alarms and paging already live."

**Why not machine learning?**
> "Error rate is one number per bucket. A robust statistic (median and MAD)
> is explainable, needs about two minutes of history instead of a training
> set, and we can state exactly why it fired. See `docs/decisions.md`."

**What if AWS is down?**
> "Delivery runs in the background. The card shows SNS `failed` with the
> error, and detection and the dashboard keep working."

**How do you avoid alerting on noise?**
> "Three guards: the MAD floor, a minimum of 5 errors and 50 lines in the
> window, and a baseline that freezes during an incident so an outage never
> becomes the new normal."
