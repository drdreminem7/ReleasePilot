"""UID-scoped, bounded reads of the one ReleasePilot lab Argo Rollout."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kubernetes import client
from kubernetes.client.exceptions import ApiException
from urllib3.exceptions import HTTPError

from releasepilot.__main__ import checked_lab_client
from releasepilot.inspection import Evidence, InspectionError
from releasepilot.lab_identity import LAB_NAMESPACE

ROLLOUT_NAME = "checkout-canary"
MAX_RUNS = 20
MAX_MEASUREMENTS = 4
MAX_EVIDENCE_BYTES = 16384
TIMEOUT_SECONDS = 5


class RolloutInspector:
    def __init__(self, uid: str, api_client: client.ApiClient) -> None:
        if not uid:
            raise InspectionError("UNREGISTERED_WORKLOAD", "Rollout UID is missing")
        self.uid = uid
        self.api = client.CustomObjectsApi(api_client)

    def _read(self) -> dict[str, Any]:
        try:
            obj = self.api.get_namespaced_custom_object(
                "argoproj.io", "v1alpha1", LAB_NAMESPACE, "rollouts", ROLLOUT_NAME,
                _request_timeout=TIMEOUT_SECONDS,
            )
        except ApiException as error:
            raise _api_error(error) from error
        except (OSError, HTTPError) as error:
            raise InspectionError("K8S_UNAVAILABLE", "Rollout API unreachable") from error
        if not isinstance(obj, dict) or obj.get("metadata", {}).get("uid") != self.uid:
            raise InspectionError("STALE_WORKLOAD_UID", "registered Rollout UID differs")
        return obj

    def status(self) -> Evidence:
        obj = self._read()
        metadata = obj.get("metadata", {})
        status = obj.get("status", {})
        return Evidence(
            source=f"rollout/{LAB_NAMESPACE}/{ROLLOUT_NAME}",
            observed_at=datetime.now(UTC).isoformat(),
            resource_uid=self.uid,
            resource_version=str(metadata.get("resourceVersion", "")),
            data={
                "phase": status.get("phase", "UNKNOWN"),
                "generation": metadata.get("generation"),
                "observed_generation": status.get("observedGeneration"),
                "ready_replicas": status.get("readyReplicas", 0),
                "desired_replicas": obj.get("spec", {}).get("replicas"),
                "stable_rs": status.get("stableRS"),
                "current_pod_hash": status.get("currentPodHash"),
                "conditions": [
                    {
                        "type": item.get("type"),
                        "status": item.get("status"),
                        "reason": item.get("reason"),
                    }
                    for item in status.get("conditions", [])[:10]
                    if isinstance(item, dict)
                ],
            },
        )

    def analysis(self) -> Evidence:
        self._read()
        try:
            listing = self.api.list_namespaced_custom_object(
                "argoproj.io", "v1alpha1", LAB_NAMESPACE, "analysisruns",
                limit=MAX_RUNS, _request_timeout=TIMEOUT_SECONDS,
            )
        except ApiException as error:
            raise _api_error(error) from error
        except (OSError, HTTPError) as error:
            raise InspectionError("K8S_UNAVAILABLE", "AnalysisRun API unreachable") from error
        if not isinstance(listing, dict) or not isinstance(listing.get("items"), list):
            raise InspectionError("K8S_INVALID_RESPONSE", "AnalysisRun list is malformed")
        runs = []
        for item in listing["items"][:MAX_RUNS]:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata", {})
            owners = metadata.get("ownerReferences", [])
            if not any(owner.get("uid") == self.uid for owner in owners if isinstance(owner, dict)):
                continue
            metric_results = []
            for metric in item.get("status", {}).get("metricResults", [])[:4]:
                metric_results.append(
                    {
                        "name": metric.get("name"),
                        "phase": metric.get("phase"),
                        "measurements": [
                            {
                                "phase": measure.get("phase"),
                                "value": str(measure.get("value", ""))[:128],
                                "started_at": measure.get("startedAt"),
                                "finished_at": measure.get("finishedAt"),
                            }
                            for measure in metric.get("measurements", [])[:MAX_MEASUREMENTS]
                        ],
                    }
                )
            runs.append(
                {
                    "name": metadata.get("name"),
                    "uid": metadata.get("uid"),
                    "resource_version": metadata.get("resourceVersion"),
                    "phase": item.get("status", {}).get("phase", "UNKNOWN"),
                    "started_at": item.get("status", {}).get("startedAt"),
                    "completed_at": item.get("status", {}).get("completedAt"),
                    "metrics": metric_results,
                }
            )
        if len(json.dumps(runs).encode("utf-8")) > MAX_EVIDENCE_BYTES:
            raise InspectionError("OUTPUT_LIMIT", "AnalysisRun evidence exceeded size limit")
        return Evidence(
            source=f"analysisruns/{LAB_NAMESPACE}/{ROLLOUT_NAME}",
            observed_at=datetime.now(UTC).isoformat(),
            resource_uid=self.uid,
            resource_version=str(listing.get("metadata", {}).get("resourceVersion", "")),
            data=runs,
            truncated=bool(listing.get("metadata", {}).get("continue"))
            or len(listing["items"]) > MAX_RUNS,
        )


def local_rollout_inspector() -> RolloutInspector:
    root = Path(__file__).resolve().parents[2]
    marker = root / ".releasepilot-lab" / "checkout-canary.uid"
    if not marker.is_file():
        raise InspectionError("UNREGISTERED_WORKLOAD", "Rollout UID marker is missing")
    return RolloutInspector(marker.read_text().strip(), checked_lab_client())


def _api_error(error: ApiException) -> InspectionError:
    code = {
        401: "K8S_UNAUTHENTICATED",
        403: "K8S_FORBIDDEN",
        404: "K8S_NOT_FOUND",
        429: "K8S_RATE_LIMITED",
    }.get(error.status, "K8S_UNAVAILABLE")
    return InspectionError(code, f"Argo read failed with HTTP {error.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read fixed ReleasePilot lab Argo evidence")
    parser.add_argument("kind", choices=["status", "analysis"])
    args = parser.parse_args()
    try:
        inspector = local_rollout_inspector()
        evidence = inspector.status() if args.kind == "status" else inspector.analysis()
    except InspectionError as error:
        print(json.dumps({"error_code": error.code}))
        return 1
    print(json.dumps(evidence.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
