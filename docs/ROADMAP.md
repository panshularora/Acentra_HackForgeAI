# ClaimsWatch roadmap

What is left to implement after the Acentra Health "Build to Care" code-a-thon (PS1), and how the project can be improved. The glance table was updated on 29 September 2026: silence, new-pattern, and flow-break detectors now live on `main` (`DETECTORS` in `detection/detector.py`). Historical design notes below the table are kept as the original plan.

The planned design for the remaining detectors is the version 2 contract in [contract.md](contract.md#version-2-template-aware-detection-additive-to-version-1).

## 1. Status at a glance

| # | Item | Status | Pull requests | What exists |
| --- | --- | --- | --- | --- |
| 1 | Per-template counting with Drain3 | Done | [#33](https://github.com/panshularora/Acentra_HackForgeAI/pull/33) | `detection/templates.py` mines templates from masked lines; `error_spike.py` scores each error template against its own median and MAD. |
| 2 | Silence detector | Done | loggen fault in [#27](https://github.com/panshularora/Acentra_HackForgeAI/pull/27) | `detection/silence.py`: per-template inter-arrival CV; `heartbeat-stop` inject from the dashboard. |
| 3 | New-pattern detector | Done | loggen fault in [#27](https://github.com/panshularora/Acentra_HackForgeAI/pull/27) | `detection/new_pattern.py`: unseen ERROR/WARN after warm-up; defers when `error_spike` already claimed the template. |
| 4 | PHI redactor test | Done | [#26](https://github.com/panshularora/Acentra_HackForgeAI/pull/26), [#34](https://github.com/panshularora/Acentra_HackForgeAI/pull/34) | `test_phi_never_reaches_the_store_the_feed_or_aws` in `test_api.py` checks the store, the WebSocket feed and AWS. #34 made the phone pattern more precise (see the note under the table). |
| 5 | Flow-break detector | Done | loggen fault in [#27](https://github.com/panshularora/Acentra_HackForgeAI/pull/27) | `detection/flow_break.py`: incomplete `claim validated` → `claim adjudicated` pairs scored with `RobustBaseline`. |
| 6 | Explainable alerts | Partly done | [#28](https://github.com/panshularora/Acentra_HackForgeAI/pull/28), [#33](https://github.com/panshularora/Acentra_HackForgeAI/pull/33) | `detector`, `template`, `baseline_band`, `observed`, `first_bad_line` and `params` are on the alert, stored in SQLite and shown on the card. They are not in the SNS/CloudWatch message, and only `error_spike` fills them. |
| 7 | Learning-state badge | Done | [#30](https://github.com/panshularora/Acentra_HackForgeAI/pull/30) | `LearningBadge.tsx`, driven by the `learning` object on each stats point and in `/api/health`. |
| 8 | Benchmark against the global control with loggen faults | Partly done | [#27](https://github.com/panshularora/Acentra_HackForgeAI/pull/27) (merged), [#35](https://github.com/panshularora/Acentra_HackForgeAI/pull/35) (draft) | loggen has five faults and a seeded `simulate()`. #35 adds the frozen `GlobalErrorRateDetector` control, `tools/benchmark.py` and `make benchmark`, but has not been merged with main or run, and no results are committed. |
| 9 | SNS on escalate and resolve | Done | [#29](https://github.com/panshularora/Acentra_HackForgeAI/pull/29), [#31](https://github.com/panshularora/Acentra_HackForgeAI/pull/31) | One message per transition with an `event` field (`opened`, `escalated`, `resolved`) and `event`, `severity`, `status` message attributes. #31 resets the delivery status to pending when a new transition is queued. |

Accepted trade-off from #34: a standalone phone-shaped sequence such as `values 200 300 4000` is still masked as `<PHONE>`. It cannot be told apart from `555 123 4567` by syntax, and for PHI a false positive is the safer mistake. Runs of plain numbers inside a longer sequence, such as `count 100 200 3000`, are no longer masked.

## 2. What is left to implement

Items 2, 3 and 5 (silence, new-pattern, flow-break) are implemented. The subsections below are the original design notes.

loggen already has the matching faults for every detector (`heartbeat-stop`, `new-error`, `flow-break`), both live (`make incident-silence`, `make incident-new`, `make incident-flow`) and in `loggen.simulate(seed)`.

All three new detectors plug into `Detector.close_bucket()` in `backend/app/detection/detector.py`: add the detector's findings to the `findings` list, add its name to `DETECTORS` (which also updates `/api/health`), and let it learn only when `learnable` is true and no incident is open, as `error_spike` does. The incident tracker already keys incidents by detector and template, so no change is needed there.

### 2.1 Silence detector (item 2)

**Design (decided).** A template with a steady cadence has not been seen for far longer than its typical gap.

- Per template, keep the last N inter-arrival gaps (time between consecutive lines of that template).
- Treat a template as steady only if it has enough gaps and their coefficient of variation (standard deviation divided by mean) is below a threshold. Bursty templates such as ordinary errors never qualify.
- At each bucket close, fire when the time since the template was last seen exceeds `max(factor * median_gap, min_seconds)`.
- Explanation: `baseline_band` in the unit `"seconds between lines"` (median gap and the firing threshold as `upper`), `observed` = seconds since last seen, `first_bad_line` = null (there is no bad line), `template` = the silent template.

**Open decision.** `close_bucket()` currently skips all detectors when the window is empty. Silence must still be evaluated then, but if the whole file stops, every steady template goes silent at once. Decide whether that produces one "log feed silent" incident or is suppressed, so it does not open one incident per heartbeat.

**Files.** New `backend/app/detection/silence.py`; `detection/detector.py`; `detection/config.py` and `app/config.py` for `SILENCE_FACTOR`, `SILENCE_MIN_SECONDS`, `SILENCE_MAX_CV`, `SILENCE_MIN_GAPS`; `docs/contract.md`, `docs/decisions.md`, README.

**Tests.** New `test_silence.py`: steady template fires after the threshold and resolves when lines return; bursty template never qualifies; `min_seconds` floor; no alert during warm-up. In `test_replay.py` or the benchmark, the `heartbeat-stop` fault from `simulate()` is detected.

**Acceptance.** `heartbeat-stop` detected on every benchmark seed; no new false alarms in normal traffic; `make check` green.

**Size.** M.

### 2.2 New-pattern detector (item 3)

**Design (decided).** An ERROR or WARN template never seen before appears more than once after the warm-up period.

- Record the set of template IDs seen during warm-up (until `learning.state == "ready"`).
- After warm-up, an ERROR/WARN template not in the set that is seen N >= 2 times opens a `new_pattern` incident. The N >= 2 rule avoids alerting on one-off lines.
- Explanation: `template`, `first_bad_line` = the first occurrence, `observed` = count so far, `baseline_band` with median 0.

**Points to settle.**

- `error_spike` can fire on the same new template (in an unmerged trial it caught `new-error` in 20 s). Decide whether `new_pattern` takes precedence for a template it owns or whether both incidents are allowed.
- Drain3 evicts least recently used clusters once `MAX_TEMPLATES` is reached, so an evicted template can come back with a new ID and look new. Keep the known set by template text as well as ID, or record evictions.
- Drain3 generalises a cluster's text as lines arrive; the cluster ID is stable, so key on the ID.

**Files.** New `backend/app/detection/new_pattern.py`; `detection/detector.py`; config for `NEW_PATTERN_MIN_COUNT` (default 2); docs as above.

**Tests.** New `test_new_pattern.py`: nothing fires during warm-up; one occurrence does not fire; two do; INFO templates never fire; a template seen during warm-up never fires. Benchmark: the `new-error` fault is detected.

**Acceptance.** `new-error` detected on every seed, with detection time reported against the `error_spike` result; no new false alarms.

**Size.** S to M.

### 2.3 Flow-break detector (item 5)

**Design (decided).** The declared pair `claim validated` followed by `claim adjudicated` stops completing.

- Pair lines by the `claim_id` parameter (Drain3 already extracts it because it varies from line to line).
- Keep a bounded map of pending `claim_id` to validation time. An adjudicated line removes its entry.
- A claim is incomplete when it is still pending after the expected delay (loggen completes within 3 s; make the timeout configurable).
- Count incomplete flows per 60 s window and score the count with the existing `RobustBaseline`, unit `"incomplete flows/60s"`. loggen leaves 2% of claims incomplete, so the baseline is not zero.
- Cap the pending map and drop the oldest entries when full, so a flood of validations cannot grow memory without bound.

**Files.** New `backend/app/detection/flow_break.py`; `detection/detector.py`; config for the pair messages, `FLOW_TIMEOUT_SECONDS` and the map cap; docs.

**Tests.** New `test_flow_break.py`: completed pairs never count; pending past the timeout counts; out-of-order arrival within the timeout is fine; map cap enforced; alert fires and resolves. Benchmark: the `flow-break` fault is detected.

**Acceptance.** `flow-break` detected on every seed; no new false alarms; memory bounded under the cap.

**Size.** M.

### 2.4 Explainable alerts in SNS and CloudWatch (item 6)

**Remaining work.** `alert_message()` in `backend/app/alerts/publisher.py` builds the SNS/CloudWatch body from a fixed list of fields and leaves out `detector`, `template`, `baseline_band`, `observed`, `first_bad_line` and `params`. Add them; they are already masked. Each new detector must fill the fields as described above.

**Files.** `backend/app/alerts/publisher.py`, `backend/tests/test_publisher.py`, the SNS section of `docs/contract.md`.

**Tests.** Extend the moto read-back test to assert the explanation fields arrive in SNS and CloudWatch, and that the PHI check still passes.

**Acceptance.** An SNS message for a DB outage carries the detector, template and band; `tools/sns_tail.py` shows them.

**Size.** S.

### 2.5 Benchmark (item 8, PR #35)

**Remaining work**, as listed in the PR:

1. `git merge origin/main` into `feat/benchmark` (main now has #33 and #34), then `make check`.
2. `make benchmark` with 5 seeds.
3. Commit the generated `docs/benchmark.md` and `docs/benchmark.json` unedited.
4. Reword the README replay sentence and test-results line to the synthetic-replay label (stream length, line count, seeds), copying numbers only from the generated output and keeping them separate from live timings. Add a one-line note that any log file can be monitored with `LOG_PATH`.
5. Mark ready and merge.

Rerun the benchmark after each new detector merges, since it reports contract detectors missing from `DETECTORS` as "not implemented".

**Acceptance.** Generated files committed as produced; README numbers match them.

**Size.** S.

## 3. Known issues and risks

**Before any live demo:** fix the demo script (item 2 below) so it matches main's current behavior.

| Issue | Evidence | Fix |
| --- | --- | --- |
| `make feed` crashes on an empty window | `tools/watch_feed.py` formats `data["error_rate"]` with `:.2%`, while `Detector.close_bucket()` sets `error_rate` to `None` when the window has no lines. | Guard the nullable rate before formatting and print a gap or `-` for empty windows. (Size: S) |
| Demo script describes behavior that main does not have | `docs/demo-script.md` promises WARNING/HIGH then CRITICAL escalation and implies heartbeat-stop and flow-break are caught; main's replay opens both incidents CRITICAL in the first bucket, those two faults produce no findings, and new-error opens WARNING. | Re-run the demo scenarios on main and rewrite the script's timings, severities and extra-fault claims before presenting it. (Size: S) |
| `/api/health` contract lists detectors that are not enabled | `docs/contract.md` lists four detectors, but `backend/app/detection/detector.py` defines `DETECTORS = ("error_spike",)` and `backend/app/api/routes.py` returns that tuple. | Update the health contract to list `error_spike` until the other detectors are implemented, then keep it synchronized with `DETECTORS`. (Size: S) |
| Replay omits live heartbeats and claim flow | `tools/replay.py:generate_log()` calls only `normal_second()` and incident injection, whereas live `loggen.Traffic.second()` separately adds heartbeat and claim-flow lines. | Generate replay traffic through the same `Traffic` path, including heartbeats and claim flow, so benchmark coverage matches live input. (Size: M) |
| Alert summary percentage is easy to misread | `detection/contributors.py:summarise()` divides the template's error lines by `error_count`, which `error_spike.py` passes as all errors in the window; the share can therefore be 39% in the replay's first bucket and 74% at peak. | Label the summary percentage explicitly as the template's share of all window errors, or show the numerator and denominator as well. (Size: S) |
| Per-template warm-up is hidden by global learning state | `KeyedBaselines` gives a template first seen during warm-up only the global history accumulated so far, while `Detector.learning.buckets_seen` reports only `_rate_baseline.sample_count`; that template can still need its own samples after the global state says ready. | Track and expose per-template readiness, or seed each template's missing warm-up windows consistently before declaring it ready. (Size: M) |
| Replay seed 42 raises one false alarm | `tools/replay.py --seed 42` on main: both incidents detected in 10 s, "False alarms outside incidents: 1". The default seed 2026 gives 0. | Print the false alarm's template and summary in `replay.py`, compare with the control in the benchmark, then tune the guard or MAD floor if it is a real weakness. Report the rate over several seeds, not one. |
| "NPI registry request failed" false alarm | One-seed trial of the template detector during benchmark work (1 false alarm in 0.83 h). Not a committed result. | Confirm with the 5-seed benchmark. If it repeats, check whether this low-volume template's baseline is too tight (Poisson floor at a small median) and raise `TEMPLATE_MAD_FLOOR` or `MIN_ERRORS` per template. |
| DB-outage alert has `params: []` | `contributors.py` keeps a parameter value only if it has at least 2 occurrences and a share of at least 50% (`PARAM_MIN_SHARE = 0.5`). No single value dominates a DB outage. | Intended for the IP case, but the card shows nothing useful here. Show the top values with their shares when none reaches 50%, labelled as such. |
| Template text is the whole masked line shape | Templates include every token of the line (`req=<*> ... ip=<IP> status=503 <*>`), so they are long and hard to read. | Show a short form (level, service and `msg`) on the card and in SNS, and keep the full template for detail. |
| StatsPoint severity and score mean different things | In `close_bucket()`, `severity` is the maximum over the per-template findings while `score`, `baseline_median` and `band_upper` are for the global error rate. A point can show CRITICAL with a low global score. | Document it in `docs/contract.md`, or split into `global_score` and `max_finding_severity` (additive fields). |
| Drain3 roughly doubles per-line cost | Engineer's replay measurement: 2.5 s to 4.3 s for 48k lines. | Acceptable at demo rates. Measure lines per second properly (see 4.7) before any production claim. |
| Current main not built with Docker | Docker was verified end to end on #32 before #33 added `drain3`; #34 has also merged since. The `heartbeat-stop` injection in Docker is also unconfirmed. | `docker compose build && docker compose up`, wait for `baseline_warm: true`, inject all five faults. |
| No CI workflow in the repository | There is no `.github/` directory. A ready workflow (backend `make check` steps plus replay, frontend lint, typecheck, test and build, and a compose build) was prepared during the build. | Add it as `.github/workflows/ci.yml` through the GitHub web UI; the GitHub CLI token used for the build has no `workflow` scope, so it cannot push workflow files. |
| Deck PR #25 is stale | It describes the old global detector on slide 3 and quotes a 20 s DB-outage detection and 150 backend tests. Main now detects the outage in 10 s and has 221 tests. | Rerun `make_evidence.py` on current main, rewrite slide 3 for per-template detection, and use benchmark numbers once #35 lands. |
| Frontend comments refer to a nonexistent `CONTRACT.md` | `frontend/src/types.ts` line 2 and `frontend/src/lib/severity.ts` line 9. | Point them at `docs/contract.md`. |
| mypy does not cover the tests | `make typecheck` runs `mypy app ../tools`; `backend/tests` is excluded. | Add `tests` to the command (and to the CI file), then fix what it reports. |
| README has no Windows run steps | The README covers Docker and a Unix `make` workflow only. | Add a Windows section: Docker Desktop for `docker compose up --build`, or WSL 2 for the `make` workflow. |
| README backend test count is stale | README says 217; `pytest` on main reports 221. | Update the test-results table, ideally from the benchmark or CI output rather than by hand. |

## 4. Further improvements

### 4.1 Validate on real labelled logs

Run the detectors on public datasets with labelled anomalies, such as HDFS_v1 and BGL from [Loghub](https://github.com/logpai/loghub), and measure detection time and precision on logs we did not write. This needs a parser adapter per dataset format and a replay mode that reads a file with its own timestamps.

### 4.2 Per-service baselines

A low-volume service that fails completely barely moves the global error rate. Per-template detection (item 1) already covers most of this: Drain3 routes on level and service first, so templates never span services, and each error template has its own baseline. What is still missing is a service-level view, for example a service whose error share rises across many templates at once, each too small to alert on its own. Add a per-service error count with its own baseline, reusing the keyed baselines in `baseline.py`.

### 4.3 Time-of-day and seasonal baselines

Claims traffic has hourly swings and busy periods such as month-end and renewal periods. The current baseline is the last 30 windows, so a normal daily ramp can look like an anomaly or hide one. Compare each window against the same hour on previous days as well as against recent history, which requires persisting baselines (see 4.6).

### 4.4 On-call feedback

Acknowledge already exists (`POST /api/alerts/{alert_id}/ack` and the button on each card). Add a manual resolve and a "not a real incident" action, record the answers with the alert in SQLite, and use them to report precision and to tune thresholds per template.

### 4.5 LLM incident summaries from masked data only

Generate a short incident summary from the masked template, the baseline band, the observed value and the top contributors, never from raw lines. Masking at the parser already guarantees that only masked text is available. This fits Acentra Health's public work on safe AI in Medicaid: in September 2025 it launched the Safe AI in Medicaid Alliance with state Medicaid agencies and Amazon Web Services among the participants ([Acentra Health announcement](https://acentra.com/news/new-medicaid-alliance-on-safe-ai)). The summary should be optional, clearly marked as generated, and shown next to the existing statistical explanation, not instead of it.

### 4.6 Routing and more inputs

- Routing: per-severity or per-service SNS topics, or a PagerDuty integration, so a WARNING does not page anyone.
- Inputs: accept a CloudWatch Logs subscription as a source, and follow multiple files, instead of one `LOG_PATH`.

### 4.7 Engineering improvements

1. **Keep detector state across restarts.** The Drain3 miner and all baselines are in memory only; `TemplateCatalog` is created without a Drain3 persistence handler. After a restart the detector is blind for about two minutes and forgets which templates existed, which would also make every template look new to the new-pattern detector. Persist the Drain3 state and the baselines (Drain3 supports file persistence) and restore them on startup.
2. **Measure throughput.** There is no published lines-per-second figure; the only number is the replay timing above. Add a load test that feeds generated lines through `Detector` and through the live tailer at increasing rates, and record the maximum sustained rate and the time taken to close a bucket at each rate.
3. **Bound alert history.** `AlertStore` in `alerts/store.py` inserts and updates but never deletes, so the SQLite file grows without limit. Add a retention setting (days or row count) and a periodic cleanup.

Log rotation and truncation are already handled and tested (`tailer.py`, `test_tailer.py`), so they are not listed here.

## 5. Suggested order for the next session

1. Build and run current main with Docker, and inject all five faults.
2. Finish benchmark PR #35: merge main, `make benchmark`, commit the generated files unedited, reword the README, merge.
3. Add the CI workflow through the GitHub UI, with `tests` added to the mypy step. Fix the `CONTRACT.md` comments and the README test count in the same pass.
4. Add the explanation fields to `alert_message()` (S).
5. Silence detector, then new-pattern, then flow-break; rerun the benchmark after each.
6. Investigate the seed-42 and "NPI registry request failed" false alarms using the benchmark output.
7. Update deck PR #25 from the new benchmark numbers.
8. Then the further improvements, starting with detector state persistence and Loghub validation.
