#!/usr/bin/env python3
"""Run a focused API health check plan and write handoff-friendly reports."""

from __future__ import annotations

import argparse
import csv
import json
import os
import ssl
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


SECRET_HEADER_NAMES = {"authorization", "cookie", "x-api-key", "api-key", "x-auth-token"}


@dataclass
class CheckResult:
    name: str
    method: str
    url: str
    ok: bool
    status: int | None
    elapsed_ms: int
    problems: list[str] = field(default_factory=list)
    response_preview: str = ""
    request_headers: list[str] = field(default_factory=list)


def load_plan(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON plan: {exc}") from exc


def build_url(base_url: str, path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        url = path_or_url
    else:
        url = urljoin(base_url.rstrip("/") + "/", path_or_url.lstrip("/"))
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")
    return url


def resolve_headers(headers: dict[str, str] | None) -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    report_keys: list[str] = []
    for key, value in (headers or {}).items():
        if isinstance(value, str) and value.startswith("env:"):
            env_name = value[4:]
            env_value = os.environ.get(env_name)
            if not env_value:
                raise ValueError(f"Header {key} expects missing env var {env_name}")
            resolved[key] = env_value
            report_keys.append(f"{key}=env:{env_name}")
        else:
            resolved[key] = str(value)
            report_keys.append(f"{key}=<masked>" if key.lower() in SECRET_HEADER_NAMES else key)
    return resolved, report_keys


def request_check(check: dict[str, Any], base_url: str, default_timeout: float) -> CheckResult:
    name = str(check.get("name", "unnamed check"))
    method = str(check.get("method", "GET")).upper()
    url = build_url(base_url, str(check.get("path") or check.get("url") or "/"))
    headers, header_report = resolve_headers(check.get("headers"))

    data = None
    if "body" in check:
        data = json.dumps(check["body"]).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    request = Request(url, data=data, method=method, headers=headers)
    timeout = float(check.get("timeout_seconds", default_timeout))
    started = time.perf_counter()
    status: int | None = None
    response_headers: dict[str, str] = {}
    response_text = ""
    transport_problem: str | None = None

    try:
        context = ssl.create_default_context()
        with urlopen(request, timeout=timeout, context=context) as response:
            status = response.status
            response_headers = dict(response.headers.items())
            response_text = response.read(250_000).decode("utf-8", errors="replace")
    except HTTPError as exc:
        status = exc.code
        response_headers = dict(exc.headers.items())
        response_text = exc.read(250_000).decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as exc:
        transport_problem = str(exc)

    elapsed_ms = int(round((time.perf_counter() - started) * 1000))
    problems = evaluate_response(check, status, response_headers, response_text, elapsed_ms)
    if transport_problem:
        problems.insert(0, f"transport error: {transport_problem}")
    return CheckResult(
        name=name,
        method=method,
        url=url,
        ok=not problems,
        status=status,
        elapsed_ms=elapsed_ms,
        problems=problems,
        response_preview=compact_preview(response_text),
        request_headers=header_report,
    )


def evaluate_response(
    check: dict[str, Any],
    status: int | None,
    headers: dict[str, str],
    text: str,
    elapsed_ms: int,
) -> list[str]:
    problems: list[str] = []

    if "expect_status" in check and status != int(check["expect_status"]):
        problems.append(f"expected status {check['expect_status']}, got {status}")

    if "max_ms" in check and elapsed_ms > int(check["max_ms"]):
        problems.append(f"expected <= {check['max_ms']} ms, got {elapsed_ms} ms")

    if "expect_body_contains" in check and str(check["expect_body_contains"]) not in text:
        problems.append(f"body missing {check['expect_body_contains']!r}")

    for key, fragment in (check.get("expect_header_contains") or {}).items():
        actual = header_lookup(headers, key)
        if actual is None:
            problems.append(f"missing header {key}")
        elif str(fragment).lower() not in actual.lower():
            problems.append(f"header {key} missing fragment {fragment!r}")

    json_expectation = check.get("expect_json")
    path_expectations = check.get("expect_json_paths") or {}
    if json_expectation is not None or path_expectations:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            problems.append("response is not valid JSON")
            return problems

        if json_expectation is not None and not partial_match(json_expectation, payload):
            problems.append("JSON body does not contain expected partial structure")

        for dotted_path, expected in path_expectations.items():
            exists, actual = read_path(payload, dotted_path)
            if not exists:
                problems.append(f"JSON path {dotted_path} is missing")
            elif actual != expected:
                problems.append(f"JSON path {dotted_path} expected {expected!r}, got {actual!r}")

    return problems


def header_lookup(headers: dict[str, str], wanted: str) -> str | None:
    wanted_lower = wanted.lower()
    for key, value in headers.items():
        if key.lower() == wanted_lower:
            return value
    return None


def partial_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and partial_match(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) < len(expected):
            return False
        return all(partial_match(exp_item, act_item) for exp_item, act_item in zip(expected, actual))
    return expected == actual


def read_path(payload: Any, dotted_path: str) -> tuple[bool, Any]:
    current = payload
    for part in dotted_path.split("."):
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return False, None
            if index < 0 or index >= len(current):
                return False, None
            current = current[index]
        elif isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        else:
            return False, None
    return True, current


def compact_preview(text: str, limit: int = 220) -> str:
    one_line = " ".join(text.strip().split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def write_reports(out_dir: Path, results: list[CheckResult]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_markdown(out_dir / "api-health-report.md", results)
    write_json(out_dir / "api-health-results.json", results)
    write_csv(out_dir / "api-health-results.csv", results)


def write_markdown(path: Path, results: list[CheckResult]) -> None:
    passed = sum(1 for result in results if result.ok)
    failed = len(results) - passed
    lines = [
        "# API Health Report",
        "",
        f"- Checks: `{len(results)}`",
        f"- Passed: `{passed}`",
        f"- Failed: `{failed}`",
        "",
        "| Check | Status | HTTP | Time | Problems |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for result in results:
        problems = "; ".join(result.problems) if result.problems else "-"
        lines.append(
            "| {name} | {state} | {status} | {elapsed} ms | {problems} |".format(
                name=escape_md(result.name),
                state="PASS" if result.ok else "FAIL",
                status=result.status if result.status is not None else "-",
                elapsed=result.elapsed_ms,
                problems=escape_md(problems),
            )
        )
    lines.extend(["", "## Details", ""])
    for result in results:
        lines.extend(
            [
                f"### {result.name}",
                "",
                f"- Method: `{result.method}`",
                f"- URL: `{result.url}`",
                f"- HTTP status: `{result.status if result.status is not None else '-'}`",
                f"- Elapsed: `{result.elapsed_ms} ms`",
                f"- Request headers: `{', '.join(result.request_headers) if result.request_headers else 'none'}`",
                f"- Result: `{'PASS' if result.ok else 'FAIL'}`",
            ]
        )
        if result.problems:
            lines.append("- Problems:")
            lines.extend(f"  - {problem}" for problem in result.problems)
        if result.response_preview:
            lines.extend(["", "Response preview:", "", "```text", result.response_preview, "```"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def write_json(path: Path, results: list[CheckResult]) -> None:
    payload = [
        {
            "name": result.name,
            "method": result.method,
            "url": result.url,
            "ok": result.ok,
            "status": result.status,
            "elapsed_ms": result.elapsed_ms,
            "problems": result.problems,
            "response_preview": result.response_preview,
            "request_headers": result.request_headers,
        }
        for result in results
    ]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_csv(path: Path, results: list[CheckResult]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "ok", "status", "elapsed_ms", "problems", "url"])
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "name": result.name,
                    "ok": result.ok,
                    "status": result.status,
                    "elapsed_ms": result.elapsed_ms,
                    "problems": "; ".join(result.problems),
                    "url": result.url,
                }
            )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run API health checks from a JSON plan.")
    parser.add_argument("plan", type=Path, help="Path to checks JSON file")
    parser.add_argument("--out", type=Path, default=Path("out"), help="Output directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    plan = load_plan(args.plan)
    base_url = str(plan.get("base_url", "")).strip()
    if not base_url:
        raise SystemExit("Plan requires base_url")
    checks = plan.get("checks")
    if not isinstance(checks, list) or not checks:
        raise SystemExit("Plan requires a non-empty checks list")

    default_timeout = float(plan.get("timeout_seconds", 5))
    results = [request_check(check, base_url, default_timeout) for check in checks]
    write_reports(args.out, results)

    passed = sum(1 for result in results if result.ok)
    failed = len(results) - passed
    print(f"checks={len(results)} passed={passed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
