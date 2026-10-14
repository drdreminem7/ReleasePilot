"""Bounded Prometheus reads from a fixed workload metric catalog."""

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from typing import Literal, TypedDict

import httpx

MetricName = Literal["scrape_up", "request_rate", "error_ratio", "latency_p95"]
Version = Literal["v1", "v2"]
ALLOWED_METRICS = frozenset({"scrape_up", "request_rate", "error_ratio", "latency_p95"})
ALLOWED_VERSIONS = frozenset({"v1", "v2"})
LOCAL_URL = "http://127.0.0.1:19090"
SERVICE_URL = "http://releasepilot-prometheus.releasepilot.svc.cluster.local:9090"
MAX_RESPONSE_BYTES = 32768
WINDOW_SECONDS = 30
TIMEOUT_SECONDS = 3.0


class MetricError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MetricResult(TypedDict):
    metric: str
    version: str
    state: Literal["KNOWN", "UNKNOWN"]
    value: float | None
    unit: str
    sample_at: str | None
    observed_at: str
    source: str
    window_seconds: int
    error_code: str | None


def _expression(metric: str, version: str) -> str:
    if metric not in ALLOWED_METRICS:
        raise MetricError("QUERY_NOT_ALLOWED")
    if version not in ALLOWED_VERSIONS:
        raise MetricError("VERSION_NOT_ALLOWED")
    target = 'job="checkout-api",namespace="releasepilot-lab"'
    if metric == "scrape_up":
        return f"up{{{target}}}"
    selector = f'{target},version="{version}"'
    all_rate = f"sum by(version)(rate(checkout_requests_total{{{selector}}}[30s]))"
    if metric == "request_rate":
        return all_rate
    if metric == "error_ratio":
        errors = f'sum by(version)(rate(checkout_requests_total{{{selector},code=~"5.."}}[30s]))'
        return f"{errors} / {all_rate}"
    buckets = (
        f"sum by(le,version)(rate(checkout_request_duration_seconds_bucket{{{selector}}}[30s]))"
    )
    return f"histogram_quantile(0.95, {buckets})"


def _unit(metric: str) -> str:
    return {
        "scrape_up": "boolean",
        "request_rate": "requests_per_second",
        "error_ratio": "ratio",
        "latency_p95": "seconds",
    }[metric]


class PrometheusReader:
    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None) -> None:
        url = base_url or os.environ.get("RELEASEPILOT_PROMETHEUS_URL", LOCAL_URL)
        if url not in {LOCAL_URL, SERVICE_URL}:
            raise MetricError("PROMETHEUS_URL_NOT_ALLOWED")
        self.base_url = url
        self.client = client or httpx.Client(
            base_url=url, timeout=TIMEOUT_SECONDS, follow_redirects=False, trust_env=False
        )
        self.owns_client = client is None

    def close(self) -> None:
        if self.owns_client:
            self.client.close()

    def __enter__(self) -> "PrometheusReader":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def query(self, metric: str, version: str = "v1") -> MetricResult:
        expression = _expression(metric, version)
        observed_at = datetime.now(UTC)
        try:
            with self.client.stream(
                "GET", f"{self.base_url}/api/v1/query", params={"query": expression}
            ) as response:
                if response.status_code != 200:
                    raise MetricError("PROMETHEUS_UNAVAILABLE")
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > MAX_RESPONSE_BYTES:
                        raise MetricError("PROMETHEUS_OUTPUT_LIMIT")
        except httpx.RequestError as error:
            raise MetricError("PROMETHEUS_UNAVAILABLE") from error
        try:
            payload = json.loads(chunks)
            if (
                not isinstance(payload, dict)
                or payload.get("status") != "success"
                or payload.get("warnings")
                or not isinstance(payload.get("data"), dict)
                or payload["data"].get("resultType") != "vector"
                or not isinstance(payload["data"].get("result"), list)
                or len(payload["data"]["result"]) > 1
            ):
                raise MetricError("PROMETHEUS_INVALID_RESPONSE")
            vector = payload["data"]["result"]
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as error:
            raise MetricError("PROMETHEUS_INVALID_RESPONSE") from error
        result = MetricResult(
            metric=metric,
            version=version,
            state="UNKNOWN",
            value=None,
            unit=_unit(metric),
            sample_at=None,
            observed_at=observed_at.isoformat(),
            source="prometheus/releasepilot/checkout-api",
            window_seconds=0 if metric == "scrape_up" else WINDOW_SECONDS,
            error_code="NO_SERIES",
        )
        if not vector:
            return result
        sample = vector[0]
        if (
            not isinstance(sample, dict)
            or not isinstance(sample.get("metric"), dict)
            or not isinstance(sample.get("value"), list)
            or len(sample["value"]) != 2
            or (metric != "scrape_up" and sample["metric"].get("version") != version)
        ):
            raise MetricError("PROMETHEUS_INVALID_RESPONSE")
        try:
            sample_at = datetime.fromtimestamp(float(sample["value"][0]), UTC)
            value = float(sample["value"][1])
        except (TypeError, ValueError, OverflowError) as error:
            raise MetricError("PROMETHEUS_INVALID_RESPONSE") from error
        if (
            not math.isfinite(value)
            or value < 0
            or (metric in {"error_ratio", "scrape_up"} and value > 1)
        ):
            result["error_code"] = "INVALID_SAMPLE"
            return result
        if abs((observed_at - sample_at).total_seconds()) > 60:
            result["error_code"] = "STALE_SAMPLE"
            return result
        result["state"] = "KNOWN"
        result["value"] = value
        result["sample_at"] = sample_at.isoformat()
        result["error_code"] = None
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Query a fixed ReleasePilot metric template")
    parser.add_argument("metric", choices=sorted(ALLOWED_METRICS))
    parser.add_argument("--version", choices=sorted(ALLOWED_VERSIONS), default="v1")
    args = parser.parse_args()
    try:
        with PrometheusReader() as reader:
            result = reader.query(args.metric, args.version)
    except MetricError as error:
        print(json.dumps({"error_code": error.code}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["state"] == "KNOWN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
