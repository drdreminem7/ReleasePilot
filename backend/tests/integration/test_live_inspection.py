import os

import pytest

from releasepilot.__main__ import local_inspector

pytestmark = pytest.mark.skipif(
    os.environ.get("RELEASEPILOT_TEST_LAB") != "1", reason="opt-in real lab test"
)


def test_registered_live_workload_reads() -> None:
    adapter = local_inspector()
    status = adapter.status()
    assert status.data["desired_replicas"] == 1
    assert status.resource_uid == adapter.workload.uid
    pods = adapter.pods()
    assert any(item["ready"] for item in pods.data)
    assert adapter.history().data["revisions"]
    name = next(item["name"] for item in pods.data if item["ready"])
    assert adapter.events(name).resource_uid
    assert adapter.logs(name).resource_uid
