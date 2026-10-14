"""Small deterministic HTTP workload for real Kubernetes failure drills."""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

MODES = {"healthy", "error-heavy", "latency-heavy", "readiness-failing"}
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0)


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "checkout_requests_total",
            "Checkout requests by response code and version.",
            labelnames=("version", "code"),
            registry=self.registry,
        )
        self.durations = Histogram(
            "checkout_request_duration_seconds",
            "Checkout request duration by version.",
            labelnames=("version",),
            buckets=BUCKETS,
            registry=self.registry,
        )

    def observe(self, version: str, status: int, duration: float) -> None:
        self.requests.labels(version=version, code=str(status)).inc()
        self.durations.labels(version=version).observe(duration)

    def initialize(self, version: str) -> None:
        for status in (200, 503):
            self.requests.labels(version=version, code=str(status)).inc(0)
        self.durations.labels(version=version)

    def render(self) -> bytes:
        return generate_latest(self.registry)


def make_handler(
    mode: str, version: str, metrics: Metrics
) -> type[BaseHTTPRequestHandler]:
    if mode not in MODES:
        raise ValueError(f"unsupported CHECKOUT_MODE: {mode}")
    if (
        not version
        or len(version) > 32
        or not version.replace("-", "").replace("_", "").isalnum()
    ):
        raise ValueError("CHECKOUT_VERSION must be a short alphanumeric label")
    metrics.initialize(version)

    class CheckoutHandler(BaseHTTPRequestHandler):
        protocol_version: ClassVar[str] = "HTTP/1.1"

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._send(200, {"status": "alive"})
            elif path == "/ready":
                ready = mode != "readiness-failing"
                self._send(200 if ready else 503, {"ready": ready})
            elif path == "/version":
                self._send(200, {"version": version, "mode": mode})
            elif path == "/checkout":
                start = time.monotonic()
                if mode == "latency-heavy":
                    time.sleep(0.4)
                status = 503 if mode == "error-heavy" else 200
                metrics.observe(version, status, time.monotonic() - start)
                self._send(status, {"ok": status == 200, "version": version})
            elif path == "/metrics":
                self._send_bytes(200, metrics.render(), CONTENT_TYPE_LATEST, close=True)
            else:
                self._send(404, {"error": "not_found"})

        def _send(self, status: int, body: dict[str, str | bool]) -> None:
            self._send_bytes(
                status,
                json.dumps(body, separators=(",", ":")).encode(),
                "application/json",
            )

        def _send_bytes(
            self, status: int, body: bytes, content_type: str, close: bool = False
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if close:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            print(f"checkout-api {self.address_string()} {format % args}", flush=True)

    return CheckoutHandler


def main() -> None:
    mode = os.environ.get("CHECKOUT_MODE", "healthy")
    version = os.environ.get("CHECKOUT_VERSION", "v1")
    handler = make_handler(mode, version, Metrics())
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(
        f"checkout-api listening on {port}, mode={mode}, version={version}", flush=True
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
