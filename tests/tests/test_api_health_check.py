import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import api_health_check
from fixture_server import FixtureHandler


class ApiHealthCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=2)

    def test_partial_json_path_and_status_checks(self):
        result = api_health_check.request_check(
            {
                "name": "orders",
                "path": "/api/orders",
                "expect_status": 200,
                "expect_json_paths": {"data.0.id": "ord_1001", "data.0.status": "paid"},
                "max_ms": 500
            },
            f"http://127.0.0.1:{self.port}",
            2,
        )
        self.assertTrue(result.ok, result.problems)
        self.assertEqual(result.status, 200)

    def test_failure_reasons_are_reported(self):
        result = api_health_check.request_check(
            {
                "name": "wrong expectation",
                "path": "/health",
                "expect_status": 200,
                "expect_json_paths": {"status": "degraded"}
            },
            f"http://127.0.0.1:{self.port}",
            2,
        )
        self.assertFalse(result.ok)
        self.assertIn("JSON path status expected 'degraded'", result.problems[0])

    def test_reports_are_written_and_exit_code_fails_on_failed_check(self):
        plan = {
            "base_url": f"http://127.0.0.1:{self.port}",
            "checks": [
                {"name": "health", "path": "/health", "expect_status": 200, "expect_json": {"status": "ok"}},
                {"name": "intentional fail", "path": "/health", "expect_status": 503}
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan_path = temp_path / "plan.json"
            out_path = temp_path / "out"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            exit_code = api_health_check.main([str(plan_path), "--out", str(out_path)])

            self.assertEqual(exit_code, 1)
            report = (out_path / "api-health-report.md").read_text(encoding="utf-8")
            results = json.loads((out_path / "api-health-results.json").read_text(encoding="utf-8"))
            self.assertIn("intentional fail", report)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[1]["status"], 200)


if __name__ == "__main__":
    unittest.main()
