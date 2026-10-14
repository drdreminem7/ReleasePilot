"""Run a checkpointed investigation and project its observed result into domain tables."""

import asyncio
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import ValidationError
from sqlalchemy import Engine, func, select

from releasepilot.db import database_url, session_factory
from releasepilot.graph import MAX_WALL_SECONDS, GraphState, build_graph
from releasepilot.inspection import InspectionError
from releasepilot.models import (
    AuditEvent,
    EvidenceItem,
    Investigation,
    InvestigationEvent,
    RegisteredWorkloadRecord,
)
from releasepilot.providers import Diagnosis, ProviderUnavailable, configured_provider
from releasepilot.read_tools import ReadOnlyTools


def _failure(engine: Engine, investigation_id: UUID, code: str, message: str) -> None:
    factory = session_factory(engine)
    with factory.begin() as db:
        item = db.scalar(
            select(Investigation)
            .where(Investigation.id == investigation_id, Investigation.status == "RUNNING")
            .with_for_update()
        )
        if item is None:
            return
        item.status = "ESCALATED"
        item.error_code = code
        item.summary = message[:2048]
        item.completed_at = datetime.now(UTC)
        next_sequence = (
            db.scalar(
                select(func.max(InvestigationEvent.sequence)).where(
                    InvestigationEvent.investigation_id == item.id
                )
            )
            or 0
        ) + 1
        db.add(
            InvestigationEvent(
                investigation_id=item.id,
                sequence=next_sequence,
                status="ESCALATED",
                message=message[:256],
            )
        )
        db.add(
            AuditEvent(
                actor_type="worker",
                actor_id=None,
                event_type="INVESTIGATION_ESCALATED",
                target_id=item.id,
                request_id=item.correlation_id,
                payload={},
                result={"error_code": code},
            )
        )


def _progress(engine: Engine, investigation_id: UUID, node_name: str, round_number: int) -> None:
    message = f"Graph {node_name} completed (round {round_number})"
    factory = session_factory(engine)
    with factory.begin() as db:
        item = db.scalar(
            select(Investigation)
            .where(Investigation.id == investigation_id, Investigation.status == "RUNNING")
            .with_for_update()
        )
        if item is None:
            return
        existing = db.scalar(
            select(InvestigationEvent.id).where(
                InvestigationEvent.investigation_id == item.id,
                InvestigationEvent.message == message,
            )
        )
        if existing is not None:
            return
        next_sequence = (
            db.scalar(
                select(func.max(InvestigationEvent.sequence)).where(
                    InvestigationEvent.investigation_id == item.id
                )
            )
            or 0
        ) + 1
        db.add(
            InvestigationEvent(
                investigation_id=item.id,
                sequence=next_sequence,
                status="RUNNING",
                message=message,
            )
        )


async def _run_graph(engine: Engine, investigation_id: UUID) -> tuple[GraphState, str]:
    factory = session_factory(engine)
    with factory() as db:
        item = db.get(Investigation, investigation_id)
        if item is None:
            raise InspectionError("INVESTIGATION_NOT_FOUND", "investigation disappeared")
        workload = db.get(RegisteredWorkloadRecord, item.workload_id)
        if workload is None or not workload.enabled:
            raise InspectionError("UNREGISTERED_WORKLOAD", "workload registration unavailable")
        thread_id = str(item.langgraph_thread_id)
        workload_id = str(workload.id)
    conninfo = database_url().replace("postgresql+psycopg://", "postgresql://", 1)
    serde = JsonPlusSerializer(allowed_msgpack_modules=None)
    async with AsyncPostgresSaver.from_conn_string(conninfo, serde=serde) as saver:
        await saver.setup()
        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 20,
        }
        checkpoint = await saver.aget(config)
        if checkpoint:
            values = checkpoint["channel_values"]
            if "outcome" in values and "diagnosis" in values and "provider_id" in values:
                return cast(GraphState, values), str(values["provider_id"])
        tools = ReadOnlyTools(workload)
        provider = configured_provider()
        graph = cast(Any, build_graph(tools, provider, saver))
        snapshot = await graph.aget_state(config)
        if snapshot.values and not snapshot.next:
            result = snapshot.values
        else:
            graph_input = None if snapshot.values else {"workload_id": workload_id}

            async def drive() -> GraphState:
                round_number = int(snapshot.values.get("round", 0)) if snapshot.values else 0
                async for update in graph.astream(graph_input, config, stream_mode="updates"):
                    for node_name, value in update.items():
                        if not isinstance(value, dict):
                            continue
                        if "round" in value:
                            round_number = int(value["round"])
                        if node_name in {
                            "validate_workload",
                            "collect_snapshot",
                            "choose_diagnostic_tools",
                            "execute_read_only_tools",
                            "analyze_evidence",
                            "produce_structured_diagnosis",
                            "validate_evidence_and_policy",
                            "finalize_report",
                        }:
                            await asyncio.to_thread(
                                _progress, engine, investigation_id, node_name, round_number
                            )
                final = await graph.aget_state(config)
                return cast(GraphState, final.values)

            result = await drive()
    return cast(GraphState, result), provider.provider_id


def _project(engine: Engine, investigation_id: UUID, state: GraphState, provider_id: str) -> None:
    diagnosis = Diagnosis.model_validate(state["diagnosis"])
    factory = session_factory(engine)
    with factory.begin() as db:
        item = db.scalar(
            select(Investigation)
            .where(Investigation.id == investigation_id, Investigation.status == "RUNNING")
            .with_for_update()
        )
        if item is None:
            return
        for evidence in state["evidence"]:
            evidence_id = UUID(evidence["id"])
            if db.get(EvidenceItem, evidence_id) is not None:
                continue
            db.add(
                EvidenceItem(
                    id=evidence_id,
                    investigation_id=item.id,
                    type=evidence["tool"],
                    source=evidence["source"],
                    observed_at=datetime.fromisoformat(evidence["observed_at"]),
                    resource_uid=evidence["resource_uid"],
                    resource_version=evidence["resource_version"],
                    content_digest=evidence["content_digest"],
                    content={"data": evidence["data"]},
                    truncated=evidence["truncated"],
                )
            )
        item.status = state["outcome"]
        item.failure_code = diagnosis.failure_category
        item.summary = diagnosis.summary
        item.error_code = None
        item.report = {**diagnosis.model_dump(mode="json"), "provider_id": provider_id}
        item.completed_at = datetime.now(UTC)
        next_sequence = (
            db.scalar(
                select(func.max(InvestigationEvent.sequence)).where(
                    InvestigationEvent.investigation_id == item.id
                )
            )
            or 0
        ) + 1
        db.add(
            InvestigationEvent(
                investigation_id=item.id,
                sequence=next_sequence,
                status=item.status,
                message="Investigation report persisted",
            )
        )
        db.add(
            AuditEvent(
                actor_type="worker",
                actor_id=None,
                event_type="INVESTIGATION_REPORTED",
                target_id=item.id,
                request_id=item.correlation_id,
                payload={"provider_id": provider_id},
                result={"status": item.status},
            )
        )


def process_investigation(engine: Engine, investigation_id: UUID) -> None:
    try:
        state, provider_id = asyncio.run(
            asyncio.wait_for(_run_graph(engine, investigation_id), MAX_WALL_SECONDS)
        )
    except ProviderUnavailable:
        _failure(
            engine,
            investigation_id,
            "PROVIDER_UNAVAILABLE",
            "Gemini provider unavailable; set GEMINI_API_KEY or select fixture mode for replay.",
        )
    except InspectionError as error:
        _failure(engine, investigation_id, error.code, "Required lab evidence was unavailable.")
    except ValidationError:
        _failure(engine, investigation_id, "INVALID_DIAGNOSIS", "Provider returned invalid output.")
    except TimeoutError:
        _failure(engine, investigation_id, "BUDGET_EXCEEDED", "Investigation time budget expired.")
    except Exception:
        _failure(engine, investigation_id, "ENGINE_FAILURE", "Investigation failed safely.")
    else:
        # Keep RUNNING on a database projection failure. The next worker loads the
        # completed checkpoint and retries the transaction without rerunning reads/LLM.
        _project(engine, investigation_id, state, provider_id)
