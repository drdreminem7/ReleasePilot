"""Argo evidence reads reject stale identities and unrelated AnalysisRuns."""

from typing import Any

import pytest
from kubernetes import client

from releasepilot.inspection import InspectionError
from releasepilot.rollout_inspection import RolloutInspector


class FakeCustomObjects:
    def get_namespaced_custom_object(self, *_args: object, **_kwargs: object) -> dict[str, Any]:
        return {
            "metadata": {"uid": "registered-uid", "resourceVersion": "9", "generation": 2},
            "spec": {"replicas": 2},
            "status": {"phase": "Degraded", "readyReplicas": 2, "stableRS": "stable-hash"},
        }

    def list_namespaced_custom_object(self, *_args: object, **_kwargs: object) -> dict[str, Any]:
        return {
            "metadata": {"resourceVersion": "10"},
            "items": [
                {
                    "metadata": {
                        "name": "own-run",
                        "uid": "run-uid",
                        "ownerReferences": [{"uid": "registered-uid"}],
                    },
                    "status": {
                        "phase": "Failed",
                        "metricResults": [{
                            "name": "candidate-error-ratio",
                            "phase": "Failed",
                            "measurements": [{"phase": "Failed", "value": "[1]"}],
                        }],
                    },
                },
                {
                    "metadata": {
                        "name": "other-run",
                        "ownerReferences": [{"uid": "other-uid"}],
                    },
                    "status": {"phase": "Successful"},
                },
            ],
        }


def test_rollout_status_and_owned_analysis_are_bounded() -> None:
    inspector = RolloutInspector("registered-uid", client.ApiClient())
    inspector.api = FakeCustomObjects()  # type: ignore[assignment]
    status = inspector.status()
    assert status.data["phase"] == "Degraded"
    assert status.resource_uid == "registered-uid"
    analysis = inspector.analysis()
    assert len(analysis.data) == 1
    assert analysis.data[0]["name"] == "own-run"
    assert analysis.data[0]["metrics"][0]["measurements"][0]["value"] == "[1]"


def test_stale_uid_fails_before_analysis_list() -> None:
    inspector = RolloutInspector("old-uid", client.ApiClient())
    inspector.api = FakeCustomObjects()  # type: ignore[assignment]
    with pytest.raises(InspectionError) as error:
        inspector.analysis()
    assert error.value.code == "STALE_WORKLOAD_UID"
