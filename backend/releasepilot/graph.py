"""Checkpointed, bounded, read-only investigation workflow."""

import asyncio
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from releasepilot.inspection import InspectionError
from releasepilot.providers import Diagnosis, DiagnosisProvider
from releasepilot.read_tools import EvidenceRecord, ReadOnlyTools

MAX_ROUNDS = 2
MAX_TOOL_CALLS = 5
MAX_WALL_SECONDS = 45


class GraphState(TypedDict, total=False):
    workload_id: str
    round: int
    selected: list[tuple[str, str | None]]
    evidence: list[EvidenceRecord]
    need_more: bool
    diagnosis: dict[str, object]
    provider_id: str
    outcome: str


def build_graph(
    tools: ReadOnlyTools,
    provider: DiagnosisProvider,
    checkpointer: BaseCheckpointSaver[Any],
    interrupt_after: list[str] | None = None,
) -> object:
    async def validate_workload(state: GraphState) -> GraphState:
        await asyncio.to_thread(tools.verify)
        return {"round": 0, "evidence": []}

    async def collect_snapshot(state: GraphState) -> GraphState:
        return {"selected": [("get_workload_status", None), ("list_workload_pods", None)]}

    async def choose_diagnostic_tools(state: GraphState) -> GraphState:
        pods = next(
            (item for item in state["evidence"] if item["tool"] == "list_workload_pods"), None
        )
        selected: list[tuple[str, str | None]] = [("get_release_history", None)]
        if pods and isinstance(pods["data"], list):
            for pod in pods["data"]:
                if isinstance(pod, dict) and not pod.get("ready"):
                    pod_name = pod.get("name")
                    if isinstance(pod_name, str):
                        selected.insert(0, ("get_pod_events", pod_name))
                        if "CrashLoopBackOff" in pod.get("waiting_reasons", []):
                            selected.append(("get_pod_logs", pod_name))
                    break
        return {"selected": selected[:3]}

    async def execute_read_only_tools(state: GraphState) -> GraphState:
        current = list(state["evidence"])
        if len(current) + len(state["selected"]) > MAX_TOOL_CALLS:
            raise InspectionError("TOOL_BUDGET", "tool call budget exceeded")
        for name, pod in state["selected"]:
            result = await asyncio.to_thread(tools.execute, name, pod)
            current.append(result)
        return {"evidence": current, "round": state["round"] + 1}

    async def analyze_evidence(state: GraphState) -> GraphState:
        status = next(
            (item for item in state["evidence"] if item["tool"] == "get_workload_status"), None
        )
        unhealthy = True
        if status and isinstance(status["data"], dict):
            data = status["data"]
            unhealthy = (
                data.get("ready_replicas") != data.get("desired_replicas")
                or data.get("updated_replicas") != data.get("desired_replicas")
                or data.get("observed_generation") != data.get("generation")
            )
        pods = next(
            (item for item in state["evidence"] if item["tool"] == "list_workload_pods"), None
        )
        if pods and isinstance(pods["data"], list):
            unhealthy = unhealthy or any(
                isinstance(pod, dict) and not pod.get("ready") for pod in pods["data"]
            )
        return {"need_more": unhealthy and state["round"] < MAX_ROUNDS}

    async def produce_structured_diagnosis(state: GraphState) -> GraphState:
        result = Diagnosis.model_validate(await provider.diagnose(state["evidence"]))
        return {"diagnosis": result.model_dump(mode="json"), "provider_id": provider.provider_id}

    async def validate_evidence_and_policy(state: GraphState) -> GraphState:
        diagnosis = Diagnosis.model_validate(state["diagnosis"])
        evidence_by_id = {item["id"]: item for item in state["evidence"]}
        supporting = set(diagnosis.supporting_evidence_ids)
        contradicting = set(diagnosis.contradicting_evidence_ids)
        if not (supporting | contradicting).issubset(evidence_by_id):
            raise InspectionError("INVALID_EVIDENCE_ID", "diagnosis cited unavailable evidence")
        if supporting & contradicting:
            raise InspectionError(
                "CONFLICTING_CITATION", "evidence cannot both support and contradict"
            )
        if (
            diagnosis.failure_category != "INSUFFICIENT_EVIDENCE"
            and not diagnosis.supporting_evidence_ids
        ):
            raise InspectionError("UNSUPPORTED_DIAGNOSIS", "diagnosis has no supporting evidence")
        cited_support = [evidence_by_id[item_id] for item_id in supporting]
        if diagnosis.failure_category == "HEALTHY":
            status = next(
                (item for item in cited_support if item["tool"] == "get_workload_status"), None
            )
            pods = next(
                (item for item in cited_support if item["tool"] == "list_workload_pods"), None
            )
            if (
                status is None
                or pods is None
                or not isinstance(status["data"], dict)
                or not isinstance(pods["data"], list)
                or not pods["data"]
                or status["truncated"]
                or pods["truncated"]
            ):
                raise InspectionError(
                    "UNSUPPORTED_DIAGNOSIS", "healthy needs complete status and pods"
                )
            counts = status["data"]
            desired = counts.get("desired_replicas")
            if (
                not isinstance(desired, int)
                or desired < 1
                or counts.get("ready_replicas") != desired
                or counts.get("updated_replicas") != desired
                or counts.get("observed_generation") != counts.get("generation")
                or any(
                    not isinstance(pod, dict) or pod.get("ready") is not True
                    for pod in pods["data"]
                )
            ):
                raise InspectionError("UNSUPPORTED_DIAGNOSIS", "cited rollout is not healthy")
            if diagnosis.recommended_action != "none":
                raise InspectionError("UNSAFE_DIAGNOSIS", "healthy rollout needs no action")
        if diagnosis.failure_category == "IMAGE_PULL_FAILURE":
            if not any(
                item["tool"] == "list_workload_pods"
                and isinstance(item["data"], list)
                and any(
                    isinstance(pod, dict)
                    and any(
                        reason in {"ErrImagePull", "ImagePullBackOff"}
                        for reason in pod.get("waiting_reasons", [])
                    )
                    for pod in item["data"]
                )
                for item in cited_support
            ):
                raise InspectionError(
                    "UNSUPPORTED_DIAGNOSIS", "image pull failure needs cited pod state"
                )
        if diagnosis.failure_category == "CRASH_LOOP":
            pods_with_crash = {
                pod.get("uid")
                for item in cited_support
                if item["tool"] == "list_workload_pods" and isinstance(item["data"], list)
                for pod in item["data"]
                if isinstance(pod, dict)
                and "CrashLoopBackOff" in pod.get("waiting_reasons", [])
                and isinstance(pod.get("restart_count"), int)
                and pod["restart_count"] > 0
            }
            if not any(
                item["tool"] == "get_pod_logs"
                and item["resource_uid"] in pods_with_crash
                and isinstance(item["data"], dict)
                and bool(item["data"].get("content"))
                for item in cited_support
            ):
                raise InspectionError("UNSUPPORTED_DIAGNOSIS", "crash loop needs cited pod and log")
        if diagnosis.failure_category == "READINESS_FAILURE":
            unready_uids = {
                pod.get("uid")
                for item in cited_support
                if item["tool"] == "list_workload_pods" and isinstance(item["data"], list)
                for pod in item["data"]
                if isinstance(pod, dict) and pod.get("ready") is False
            }
            if not any(
                item["tool"] == "get_pod_events"
                and isinstance(item["data"], list)
                and any(
                    isinstance(event, dict)
                    and event.get("reason") == "Unhealthy"
                    and event.get("pod_uid") in unready_uids
                    for event in item["data"]
                )
                for item in cited_support
            ):
                raise InspectionError(
                    "UNSUPPORTED_DIAGNOSIS", "readiness failure needs cited pod and event"
                )
        if diagnosis.failure_category == "INSUFFICIENT_EVIDENCE":
            if diagnosis.recommended_action != "escalate" or diagnosis.confidence != "low":
                raise InspectionError("UNSAFE_DIAGNOSIS", "insufficient evidence must escalate")
        outcome = (
            "ESCALATED" if diagnosis.failure_category == "INSUFFICIENT_EVIDENCE" else "COMPLETED"
        )
        return {"outcome": outcome}

    async def finalize_report(state: GraphState) -> GraphState:
        return {"outcome": state["outcome"]}

    builder = StateGraph(GraphState)
    builder.add_node("validate_workload", validate_workload)
    builder.add_node("collect_snapshot", collect_snapshot)
    builder.add_node("choose_diagnostic_tools", choose_diagnostic_tools)
    builder.add_node("execute_read_only_tools", execute_read_only_tools)
    builder.add_node("analyze_evidence", analyze_evidence)
    builder.add_node("produce_structured_diagnosis", produce_structured_diagnosis)
    builder.add_node("validate_evidence_and_policy", validate_evidence_and_policy)
    builder.add_node("finalize_report", finalize_report)
    builder.add_edge(START, "validate_workload")
    builder.add_edge("validate_workload", "collect_snapshot")
    builder.add_edge("collect_snapshot", "execute_read_only_tools")
    builder.add_edge("execute_read_only_tools", "analyze_evidence")
    builder.add_conditional_edges(
        "analyze_evidence",
        lambda state: (
            "choose_diagnostic_tools" if state["need_more"] else "produce_structured_diagnosis"
        ),
    )
    builder.add_edge("choose_diagnostic_tools", "execute_read_only_tools")
    builder.add_edge("produce_structured_diagnosis", "validate_evidence_and_policy")
    builder.add_edge("validate_evidence_and_policy", "finalize_report")
    builder.add_edge("finalize_report", END)
    return builder.compile(checkpointer=checkpointer, interrupt_after=interrupt_after)
