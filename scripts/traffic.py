"""Bounded loopback traffic generator for the guarded ReleasePilot lab."""

import argparse
import json
import time
from urllib.error import HTTPError
from urllib.request import urlopen

URLS = {
    "sample": "http://127.0.0.1:18080/checkout",
    "canary": "http://127.0.0.1:18081/checkout",
}


def run(duration: int, rps: int, target_name: str = "sample") -> dict[str, float | int]:
    url = URLS[target_name]
    total = duration * rps
    statuses: dict[int, int] = {}
    elapsed: list[float] = []
    started = time.monotonic()
    for index in range(total):
        target = started + index / rps
        time.sleep(max(0.0, target - time.monotonic()))
        before = time.monotonic()
        try:
            with urlopen(url, timeout=3) as response:
                status = response.status
                response.read(2048)
        except HTTPError as error:
            status = error.code
            error.read(2048)
        statuses[status] = statuses.get(status, 0) + 1
        elapsed.append(time.monotonic() - before)
    return {
        "requests": total,
        "http_200": statuses.get(200, 0),
        "http_503": statuses.get(503, 0),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "max_request_seconds": round(max(elapsed), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send bounded checkout requests to lab port-forward"
    )
    parser.add_argument("--duration", type=int, default=40)
    parser.add_argument("--rps", type=int, default=2)
    parser.add_argument("--target", choices=sorted(URLS), default="sample")
    args = parser.parse_args()
    if not 30 <= args.duration <= 60 or not 1 <= args.rps <= 10:
        parser.error("duration must be 30–60 seconds and rps 1–10")
    print(json.dumps(run(args.duration, args.rps, args.target), sort_keys=True))


if __name__ == "__main__":
    main()
