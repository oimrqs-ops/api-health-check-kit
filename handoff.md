# Handoff: API Health Check Kit

## Input

- JSON check plan with base URL, endpoint paths, expected status codes, JSON field checks, text/header checks, and response time budgets.
- Optional request headers through environment variables for authorized test endpoints.

## Deliverable

- `api_health_check.py` CLI runner.
- `api-health-report.md` for human review.
- `api-health-results.json` and `api-health-results.csv` for machine-readable follow-up.
- Local fixture server and tests so the behavior is reproducible without a vendor account.

## Acceptance check

```bash
python3 -m unittest discover -s tests
python3 fixture_server.py --port 8797
python3 api_health_check.py checks.example.json --out out
```

The example check plan intentionally leaves one failing check so the client can see failure evidence in the report. In a real handoff, the failing sample would be replaced with the client's actual expected state.

## Remaining risk

- Production endpoints may require allowlisting, staging credentials, or 2FA-gated sessions. Those should be handled through the client's normal access process, never by committing secrets into this repo.
- This is not a load test or security scanner. It is a focused health check and handoff tool.
