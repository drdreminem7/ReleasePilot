"""Metric reads are named, bounded, and preserve unknown results."""

from datetime import UTC, datetime

import httpx
import pytest

from releasepilot.prometheus_query import MetricError, PrometheusReader


def _reader(result: list[object], *, status: int = 200) -> PrometheusReader:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/query"
        assert request.url.params.get("query")
        return httpx.Response(
            status,
            json={"status": "success", "data": {"resultType": "vector", "result": result}},
        )

    return PrometheusReader(client=httpx.Client(transport=httpx.MockTransport(respond)))


def test_empty_metric_series_is_unknown_not_zero() -> None:
    reader = _reader([])
    result = reader.query("request_rate", "v1")
    assert result["state"] == "UNKNOWN"
    assert result["value"] is None
    assert result["error_code"] == "NO_SERIES"
    assert result["sample_at"] is None
    assert result["source"] == "prometheus/releasepilot/checkout-api"
    reader.client.close()


def test_named_template_returns_timed_sample() -> None:
    now = datetime.now(UTC).timestamp()
    reader = _reader([{"metric": {"version": "v1"}, "value": [now, "0.25"]}])
    result = reader.query("error_ratio", "v1")
    assert result["state"] == "KNOWN"
    assert result["value"] == 0.25
    assert result["sample_at"] is not None
    assert result["window_seconds"] == 30
    reader.client.close()


def test_arbitrary_promql_and_version_are_rejected_before_transport() -> None:
    reader = _reader([])
    with pytest.raises(MetricError) as invalid_query:
        reader.query('up{job="other"}')
    assert invalid_query.value.code == "QUERY_NOT_ALLOWED"
    with pytest.raises(MetricError) as invalid_version:
        reader.query("request_rate", 'v1"} or up')
    assert invalid_version.value.code == "VERSION_NOT_ALLOWED"
    reader.client.close()


def test_nonfinite_metric_is_unknown() -> None:
    now = datetime.now(UTC).timestamp()
    reader = _reader([{"metric": {"version": "v1"}, "value": [now, "NaN"]}])
    result = reader.query("error_ratio")
    assert result["state"] == "UNKNOWN"
    assert result["value"] is None
    assert result["error_code"] == "INVALID_SAMPLE"
    reader.client.close()


def test_prometheus_failure_is_not_data() -> None:
    reader = _reader([], status=503)
    with pytest.raises(MetricError) as error:
        reader.query("request_rate")
    assert error.value.code == "PROMETHEUS_UNAVAILABLE"
    reader.client.close()


def test_stale_sample_is_unknown() -> None:
    reader = _reader([{"metric": {"version": "v1"}, "value": [1, "2"]}])
    result = reader.query("request_rate")
    assert result["state"] == "UNKNOWN" and result["value"] is None
    assert result["error_code"] == "STALE_SAMPLE"
    reader.client.close()


def test_large_response_is_rejected() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 32769)

    reader = PrometheusReader(client=httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(MetricError) as error:
        reader.query("scrape_up")
    assert error.value.code == "PROMETHEUS_OUTPUT_LIMIT"
    reader.client.close()


