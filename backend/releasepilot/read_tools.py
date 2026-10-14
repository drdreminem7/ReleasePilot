"""Fixed, bounded Kubernetes reads available to the investigation graph."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal, TypedDict
from uuid import uuid4

from releasepilot.__main__ import local_inspector
from releasepilot.inspection import Evidence, InspectionError, KubernetesInspector
from releasepilot.lab_identity import LAB_NAMESPACE
from releasepilot.models import RegisteredWorkloadRecord
from releasepilot.prometheus_query import MetricError, PrometheusReader
from releasepilot.rollout_inspection import ROLLOUT_NAME, RolloutInspector, local_rollout_inspector

ToolName = Literal[
    "get_workload_status",
    "list_workload_pods",
    "get_pod_events",
    "get_pod_logs",
    "get_release_history",
    "query_workload_metric",
    "get_rollout_analysis",
]
ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "get_workload_status",
        "list_workload_pods",
        "get_pod_events",
        "get_pod_logs",
        "get_release_history",
        "query_workload_metric",
        "get_rollout_analysis",
    }
)
MAX_EVIDENCE_BYTES = 16384


class EvidenceRecord(TypedDict):
    id: str
    tool: str
    source: str
    observed_at: str
    resource_uid: str
    resource_version: str
    data: object
    truncated: bool
    content_digest: str


class ReadOnlyTools:
    def __init__(self, workload: RegisteredWorkloadRecord) -> None:
        root = Path(__file__).resolve().parents[2]
        fingerprint = (root / ".releasepilot-lab" / "cluster-uid").read_text().strip()
        if workload.cluster_fingerprint != fingerprint or workload.namespace != LAB_NAMESPACE:
            raise InspectionError("STALE_WORKLOAD_UID", "registered identity differs from lab")
        self.inspector: KubernetesInspector | None = None
        self.rollout: RolloutInspector | None = None
        if workload.kind == "Deployment":
            inspector = local_inspector()
            if workload.name != inspector.workload.name or workload.uid != inspector.workload.uid:
                raise InspectionError("STALE_WORKLOAD_UID", "registered identity differs from lab")
            self.inspector = inspector
        elif workload.kind == "Rollout":
            rollout = local_rollout_inspector()
            if workload.name != ROLLOUT_NAME or workload.uid != rollout.uid:
                raise InspectionError(
                    "STALE_WORKLOAD_UID", "registered identity differs from Rollout"
                )
            self.rollout = rollout
        else:
            raise InspectionError("UNREGISTERED_WORKLOAD", "unsupported registered kind")

    def verify(self) -> None:
        if self.rollout is not None:
            self.rollout.status()
        elif self.inspector is not None:
            self.inspector.status()

    def execute(
        self, tool: str, pod_name: str | None = None, version: str = "v1"
    ) -> EvidenceRecord:
        if tool not in ALLOWED_TOOLS:
            raise InspectionError("TOOL_NOT_ALLOWED", "tool is outside read-only allowlist")
        if tool == "get_rollout_analysis":
            if self.rollout is None:
                raise InspectionError("TOOL_NOT_AVAILABLE", "analysis requires a Rollout")
            evidence = self.rollout.analysis()
        elif tool == "get_workload_status" and self.rollout is not None:
            evidence = self.rollout.status()
        elif self.inspector is None:
            raise InspectionError("TOOL_NOT_AVAILABLE", "tool is unavailable for a Rollout")
        elif tool == "get_workload_status":
            evidence = self.inspector.status()
        elif tool == "list_workload_pods":
            evidence = self.inspector.pods()
        elif tool == "get_release_history":
            evidence = self.inspector.history()
        elif tool == "query_workload_metric":
            if not pod_name:
                raise InspectionError("INVALID_METRIC", "metric catalog name is required")
            try:
                with PrometheusReader() as reader:
                    result = reader.query(pod_name, version)
            except MetricError as error:
                raise InspectionError(error.code, "metric read failed") from error
            evidence = Evidence(
                source=result["source"],
                observed_at=result["observed_at"],
                resource_uid=self.inspector.workload.uid,
                resource_version=result["sample_at"] or "unknown",
                data=result,
            )
        elif tool == "get_pod_events":
            if not pod_name:
                raise InspectionError("INVALID_POD", "pod name is required")
            evidence = self.inspector.events(pod_name)
        else:
            if not pod_name:
                raise InspectionError("INVALID_POD", "pod name is required")
            evidence = self.inspector.logs(pod_name)
        content = json.dumps(evidence.data, sort_keys=True, default=str).encode("utf-8")
        if len(content) > MAX_EVIDENCE_BYTES:
            raise InspectionError("OUTPUT_LIMIT", "read exceeded evidence size limit")
        datetime.fromisoformat(evidence.observed_at)
        return EvidenceRecord(
            id=str(uuid4()),
            tool=tool,
            source=evidence.source,
            observed_at=evidence.observed_at,
            resource_uid=evidence.resource_uid,
            resource_version=evidence.resource_version,
            data=evidence.data,
            truncated=evidence.truncated,
            content_digest=hashlib.sha256(content).hexdigest(),
        )
