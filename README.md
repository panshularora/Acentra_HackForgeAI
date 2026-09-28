# ClaimsWatch

When a Medicaid eligibility service starts failing, the on-call engineer learns within seconds what is failing and where, before members are turned away at the pharmacy.

ClaimsWatch tails a live application log, learns what a normal error rate looks like, flags statistically significant deviations with a severity level, streams them to a dashboard over WebSockets and forwards them to AWS (SNS and CloudWatch Logs).

Built for the Acentra Health "Build to Care" code-a-thon (problem statement PS1: Real-Time Log Anomaly Detector with Alert Feed).

> Work in progress. The full documentation lands with the detection, ingest and AWS delivery changes.

## Quick start (backend)

```bash
make install   # create backend/.venv and install dependencies
make dev       # run the API on http://localhost:8000
curl localhost:8000/api/health
```

## License

MIT, see [LICENSE](LICENSE).
