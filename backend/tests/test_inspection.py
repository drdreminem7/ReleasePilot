from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from kubernetes.client.exceptions import ApiException

from releasepilot.inspection import InspectionError, KubernetesInspector, RegisteredWorkload


def workload(uid: str = "deployment-uid") -> RegisteredWorkload:
    return RegisteredWorkload("releasepilot-lab", "checkout-api", uid)


def deployment(uid: str = "deployment-uid") -> NS:
    return NS(
        metadata=NS(uid=uid, resource_version="12", generation=2),
        spec=NS(replicas=1),
        status=NS(
            observed_generation=2,
            ready_replicas=1,
            updated_replicas=1,
            conditions=[NS(type="Available", status="True", reason="MinimumReplicasAvailable")],
        ),
    )


def pod(name: str = "checkout-api-abc-123") -> NS:
    return NS(
        metadata=NS(name=name, uid="pod-uid", resource_version="15"),
        status=NS(
            phase="Running",
            container_statuses=[NS(ready=True, restart_count=0, state=NS(waiting=None))],
        ),
    )


def inspector() -> KubernetesInspector:
    result = KubernetesInspector(workload(), Mock())
    result.apps = Mock()
    result.core = Mock()
    result.apps.read_namespaced_deployment.return_value = deployment()
    result.core.list_namespaced_pod.return_value = NS(
        metadata=NS(resource_version="14", _continue=None), items=[pod()]
    )
    return result


@pytest.mark.parametrize(
    ("namespace", "name"), [("default", "checkout-api"), ("releasepilot-lab", "other")]
)
def test_unregistered_workload_is_rejected(namespace: str, name: str) -> None:
    with pytest.raises(InspectionError, match="registered"):
        RegisteredWorkload(namespace, name, "uid")


def test_status_has_resource_version_and_bounded_fields() -> None:
    adapter = inspector()
    result = adapter.status()
    assert result.resource_uid == "deployment-uid"
    assert result.resource_version == "12"
    assert result.data["ready_replicas"] == 1
    assert "spec" not in result.as_dict()
    adapter.apps.read_namespaced_deployment.assert_called_once_with(
        "checkout-api", "releasepilot-lab", _request_timeout=5
    )


def test_stale_workload_fails_closed() -> None:
    adapter = inspector()
    adapter.apps.read_namespaced_deployment.return_value = deployment("replacement-uid")
    with pytest.raises(InspectionError) as error:
        adapter.pods()
    assert error.value.code == "STALE_WORKLOAD_UID"
    adapter.core.list_namespaced_pod.assert_not_called()


def test_forbidden_and_disconnect_are_distinct() -> None:
    adapter = inspector()
    adapter.apps.read_namespaced_deployment.side_effect = ApiException(status=403)
    with pytest.raises(InspectionError) as error:
        adapter.status()
    assert error.value.code == "K8S_FORBIDDEN"
    adapter.apps.read_namespaced_deployment.side_effect = OSError("socket closed")
    with pytest.raises(InspectionError) as error:
        adapter.status()
    assert error.value.code == "K8S_UNAVAILABLE"


def test_pod_selector_is_fixed_and_unknown_pod_cannot_read_logs() -> None:
    adapter = inspector()
    assert adapter.pods().data[0]["name"] == "checkout-api-abc-123"
    adapter.core.list_namespaced_pod.assert_called_with(
        "releasepilot-lab", label_selector="app=checkout-api", limit=20, _request_timeout=5
    )
    with pytest.raises(InspectionError) as error:
        adapter.logs("checkout-api-unregistered")
    assert error.value.code == "INVALID_POD"
    adapter.core.read_namespaced_pod_log.assert_not_called()


def test_logs_are_bounded_and_redacted() -> None:
    adapter = inspector()
    adapter.core.read_namespaced_pod_log.return_value = "token=abc password: xyz normal event"
    result = adapter.logs("checkout-api-abc-123")
    assert "abc" not in result.data["content"]
    assert "xyz" not in result.data["content"]
    assert "normal event" in result.data["content"]
    adapter.core.read_namespaced_pod_log.assert_called_once_with(
        "checkout-api-abc-123",
        "releasepilot-lab",
        container="checkout-api",
        tail_lines=50,
        limit_bytes=8192,
        since_seconds=3600,
        timestamps=True,
        _request_timeout=5,
    )


def test_events_are_pod_scoped_and_redacted() -> None:
    adapter = inspector()
    adapter.core.list_namespaced_event.return_value = NS(
        metadata=NS(resource_version="20", _continue=None),
        items=[
            NS(
                message="Failed secret=abc",
                reason="Failed",
                type="Warning",
                last_timestamp=datetime.now(UTC),
                event_time=None,
                involved_object=NS(uid="pod-uid"),
            )
        ],
    )
    result = adapter.events("checkout-api-abc-123")
    assert result.resource_uid == "pod-uid"
    assert "abc" not in result.data[0]["message"]
    adapter.core.list_namespaced_event.assert_called_once_with(
        "releasepilot-lab",
        field_selector="involvedObject.name=checkout-api-abc-123",
        limit=20,
        _request_timeout=5,
    )


def test_release_history_excludes_other_owners() -> None:
    adapter = inspector()

    def replica_set(owner: str, name: str) -> NS:
        return NS(
            metadata=NS(
                name=name,
                uid=f"{name}-uid",
                owner_references=[NS(uid=owner)],
                annotations={"deployment.kubernetes.io/revision": "1"},
            ),
            spec=NS(template=NS(spec=NS(containers=[NS(image="releasepilot/checkout-api:m1")]))),
        )

    adapter.apps.list_namespaced_replica_set.return_value = NS(
        metadata=NS(resource_version="21", _continue=None),
        items=[replica_set("deployment-uid", "ours"), replica_set("other", "not-ours")],
    )
    result = adapter.history()
    assert [item["name"] for item in result.data["revisions"]] == ["ours"]


def test_oversized_logs_are_marked_truncated() -> None:
    adapter = inspector()
    adapter.core.read_namespaced_pod_log.return_value = "x" * 9000
    result = adapter.logs("checkout-api-abc-123")
    assert result.truncated
    assert len(result.data["content"].encode()) <= 8192
