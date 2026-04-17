# API Health Check Kit

Small dependency-free Python kit for checking HTTP APIs, webhook endpoints, and backoffice integration paths before handing work back to a client.

It is built for a focused 1-day delivery slice:

- read a JSON check plan;
- call each endpoint with safe timeouts;
- validate status codes, response time budgets, headers, body text, and partial JSON fields;
- write a Markdown report plus machine-readable JSON/CSV output;
- return a non-zero exit code when any required check fails.

## Why this exists

Many integration/debugging jobs start with vague symptoms: "the webhook is unstable", "the dashboard sometimes fails", "the API stopped syncing", or "the vendor says it is fine." This kit turns that into a reviewable health report with exact checks, timings, and failure reasons.

## Files

- `api_health_check.py` - CLI runner and validation engine.
- `checks.example.json` - sample check plan.
- `fixture_server.py` - local HTTP fixture for demo/testing.
- `tests/test_api_health_check.py` - standard-library tests.
- `handoff.md` - example client handoff note.

## Usage

Start the fixture server:

```bash
python3 fixture_server.py --port 8797
```

Run the checks in another terminal:

```bash
python3 api_health_check.py checks.example.json --out out
```

Expected output:

```text
checks=4 passed=3 failed=1
```

The sample intentionally includes one failing check so the report shows how problems are captured.

Generated files:

- `out/api-health-report.md`
- `out/api-health-results.json`
- `out/api-health-results.csv`

## Config shape

```json
{
  "base_url": "http://127.0.0.1:8797",
  "timeout_seconds": 2,
  "checks": [
    {
      "name": "health endpoint",
      "method": "GET",
      "path": "/health",
      "expect_status": 200,
      "expect_json": { "status": "ok" },
      "max_ms": 300
    }
  ]
}
```

Optional fields per check:

- `headers` - request headers. Values like `env:API_TOKEN` are loaded from environment variables and masked in reports.
- `body` - JSON body for POST/PUT/PATCH requests.
- `expect_status` - exact expected HTTP status code.
- `expect_body_contains` - string that must appear in the response body.
- `expect_header_contains` - object of header fragments to check.
- `expect_json` - partial JSON object/list expected in the response.
- `expect_json_paths` - simple path assertions such as `data.0.id`.
- `max_ms` - response time budget.

## Boundary

This is for endpoints the client owns, controls, or is authorized to test. It is not a scanner, load tester, credential harvester, CAPTCHA bypass, or hidden API probe. Do not commit tokens or production secrets into check plans; use environment variables for sensitive header values.
