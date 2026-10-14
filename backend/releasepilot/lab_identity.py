"""Fail-closed identity checks shared by local lab tooling."""

from dataclasses import dataclass

CLUSTER_NAME = "releasepilot-lab"
CONTEXT_NAME = f"k3d-{CLUSTER_NAME}"
CONTROL_NAMESPACE = "releasepilot"
LAB_NAMESPACE = "releasepilot-lab"


class LabIdentityError(ValueError):
    """The selected cluster is not the dedicated ReleasePilot lab."""


@dataclass(frozen=True)
class LabIdentity:
    context: str
    cluster_name: str
    fingerprint: str

    def verify(self, expected_fingerprint: str) -> None:
        if self.context != CONTEXT_NAME or self.cluster_name != CLUSTER_NAME:
            raise LabIdentityError("unexpected Kubernetes context or cluster name")
        if not expected_fingerprint or self.fingerprint != expected_fingerprint:
            raise LabIdentityError("missing or mismatched lab fingerprint")
