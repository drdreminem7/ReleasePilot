import json
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from app.main import Metrics, make_handler
from prometheus_client.parser import text_string_to_metric_families


@contextmanager
def running(mode: str):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(mode, "v1", Metrics()))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def request(url: str) -> tuple[int, bytes]:
    try:
        with urlopen(url, timeout=2) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def sample_value(raw: bytes, name: str, labels: dict[str, str]) -> float:
    for family in text_string_to_metric_families(raw.decode()):
        for sample in family.samples:
            if sample.name == name and sample.labels == labels:
                return float(sample.value)
    raise AssertionError(f"missing {name} with labels {labels}")


def test_healthy_endpoints_and_metrics() -> None:
    with running("healthy") as url:
        assert request(url + "/health")[0] == 200
        assert json.loads(request(url + "/ready")[1]) == {"ready": True}
        assert json.loads(request(url + "/version")[1]) == {"version": "v1", "mode": "healthy"}
        assert request(url + "/checkout")[0] == 200
        status, metrics = request(url + "/metrics")
        assert status == 200
        assert sample_value(metrics, "checkout_requests_total", {"version": "v1", "code": "200"}) == 1
        with urlopen(url + "/metrics", timeout=2) as response:
            assert response.headers["Connection"] == "close"


def test_error_heavy_is_observable() -> None:
    with running("error-heavy") as url:
        assert request(url + "/checkout")[0] == 503
        assert (
            sample_value(
                request(url + "/metrics")[1],
                "checkout_requests_total",
                {"version": "v1", "code": "503"},
            )
            == 1
        )


def test_readiness_failing_is_observable() -> None:
    with running("readiness-failing") as url:
        assert json.loads(request(url + "/ready")[1]) == {"ready": False}
        assert request(url + "/ready")[0] == 503
        assert request(url + "/health")[0] == 200


def test_latency_heavy_is_observable() -> None:
    with running("latency-heavy") as url:
        assert request(url + "/checkout")[0] == 200
        metrics = request(url + "/metrics")[1]
        assert sample_value(
            metrics, "checkout_request_duration_seconds_bucket", {"version": "v1", "le": "0.25"}
        ) == 0
        assert sample_value(
            metrics, "checkout_request_duration_seconds_bucket", {"version": "v1", "le": "0.5"}
        ) == 1


def test_invalid_mode_refuses_start() -> None:
    try:
        make_handler("surprise", "v1", Metrics())
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("invalid mode was accepted")

