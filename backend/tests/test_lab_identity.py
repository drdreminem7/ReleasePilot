import pytest

from releasepilot.lab_identity import LabIdentity, LabIdentityError


def test_explicit_identity_passes() -> None:
    LabIdentity("k3d-releasepilot-lab", "releasepilot-lab", "uid-123").verify("uid-123")


@pytest.mark.parametrize(
    ("context", "cluster", "actual", "expected"),
    [
        ("personal", "releasepilot-lab", "uid-123", "uid-123"),
        ("k3d-releasepilot-lab", "personal", "uid-123", "uid-123"),
        ("k3d-releasepilot-lab", "releasepilot-lab", "uid-123", "uid-other"),
        ("k3d-releasepilot-lab", "releasepilot-lab", "uid-123", ""),
    ],
)
def test_identity_rejects_any_mismatch(
    context: str, cluster: str, actual: str, expected: str
) -> None:
    with pytest.raises(LabIdentityError):
        LabIdentity(context, cluster, actual).verify(expected)
