"""Replay scores must not reward missing evidence or safe abstention on failures."""

import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from releasepilot.evaluation import (
    Catalog,
    load_catalog,
    replay_evidence,
    run_case,
    run_catalog,
    score_case,
)
from releasepilot.providers import Diagnosis, FixtureProvider
from releasepilot.read_tools import EvidenceRecord


def _case(case_id: str) -> tuple[Catalog, int]:
    catalog = load_catalog()
    return catalog, next(index for index, item in enumerate(catalog.cases) if item.id == case_id)


def test_six_replay_cases_pass_but_are_labeled_synthetic() -> None:
    catalog = load_catalog()
    first = asyncio.run(run_catalog(catalog, FixtureProvider(), "a" * 64))
    second = asyncio.run(run_catalog(catalog, FixtureProvider(), "a" * 64))
    assert len(catalog.cases) == 6
    assert first["passed"] == second["passed"] == 6
    assert [item["scores"] for item in first["results"]] == [
        item["scores"] for item in second["results"]
    ]
    assert first["source_mode"] == "synthetic_replay"
    assert first["model_mode"] == "deterministic_fixture"
    assert first["live_cluster_observed"] is False
    assert first["token_usage"] is None


def test_correct_category_with_missing_required_event_fails() -> None:
    catalog, index = _case("S01")
    case = deepcopy(catalog.cases[index])
    case.observations = [item for item in case.observations if item.tool != "get_pod_events"]
    result = asyncio.run(run_case(catalog, case, FixtureProvider()))
    assert result["observed_category"] == "IMAGE_PULL_FAILURE"
    assert result["missing_signals"] == ["failed_image_event"]
    assert result["scores"]["diagnosis_correctness"] == 0
    assert result["scores"]["evidence_fidelity"] == 0
    assert result["pass"] is False


def test_abstention_does_not_count_as_correct_failure_diagnosis() -> None:
    class AbstainingProvider:
        provider_id = "abstaining-fixture"

        async def diagnose(self, evidence: list[EvidenceRecord]) -> Diagnosis:
            return Diagnosis(
                failure_category="INSUFFICIENT_EVIDENCE",
                summary="The provider declines to diagnose this case.",
                hypotheses=[],
                supporting_evidence_ids=[],
                contradicting_evidence_ids=[],
                confidence="low",
                recommended_action="escalate",
                risk_explanation="No action is justified.",
                limitations="Deliberate test abstention.",
            )

    catalog, index = _case("S02")
    result = asyncio.run(run_case(catalog, catalog.cases[index], AbstainingProvider()))
    assert result["scores"]["diagnosis_correctness"] == 0
    assert result["scores"]["escalation_accuracy"] == 0
    assert result["pass"] is False


def test_nonexistent_citation_fails_fidelity() -> None:
    catalog, index = _case("S03")
    evidence = replay_evidence(catalog, catalog.cases[index])
    diagnosis = Diagnosis(
        failure_category="READINESS_FAILURE",
        summary="The candidate readiness probe is failing.",
        hypotheses=[],
        supporting_evidence_ids=[str(uuid4())],
        contradicting_evidence_ids=[],
        confidence="high",
        recommended_action="escalate",
        risk_explanation="No action is justified.",
        limitations="Deliberate invalid citation.",
    )
    result = score_case(catalog, catalog.cases[index], evidence, diagnosis, 1.0)
    assert result["scores"]["evidence_fidelity"] == 0
    assert result["scores"]["unsupported_claims"] == 0
    assert result["pass"] is False


def test_permission_denial_and_malicious_log_only_pass_on_escalation() -> None:
    catalog = load_catalog()
    for case in catalog.cases:
        if case.id in {"S07", "S08", "S09"}:
            result = asyncio.run(run_case(catalog, case, FixtureProvider()))
            assert result["observed_category"] == "INSUFFICIENT_EVIDENCE"
            assert result["observed_action"] == "escalate"
            assert result["pass"] is True


def test_unallowlisted_fixture_tool_is_rejected() -> None:
    catalog = load_catalog().model_dump(mode="json")
    catalog["cases"][0]["allowed_tools"].append("kubectl_exec")
    with pytest.raises(ValidationError):
        Catalog.model_validate(catalog)
