"""Read-only `python -m releasepilot inspect ...` CLI."""

import argparse
import json
import sys
from pathlib import Path

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException
from urllib3.exceptions import HTTPError

from releasepilot.inspection import InspectionError, KubernetesInspector, RegisteredWorkload
from releasepilot.lab_identity import (
    CLUSTER_NAME,
    CONTEXT_NAME,
    LAB_NAMESPACE,
    LabIdentity,
    LabIdentityError,
)


def local_inspector() -> KubernetesInspector:
    root = Path(__file__).resolve().parents[2]
    workload_marker = root / ".releasepilot-lab" / "checkout-api.uid"
    if not workload_marker.is_file():
        raise InspectionError("UNREGISTERED_WORKLOAD", "lab or workload UID marker is missing")
    workload_uid = workload_marker.read_text().strip()
    if not workload_uid:
        raise InspectionError("UNREGISTERED_WORKLOAD", "lab or workload UID marker is empty")
    api_client = checked_lab_client()
    return KubernetesInspector(
        RegisteredWorkload(LAB_NAMESPACE, "checkout-api", workload_uid), api_client
    )


def checked_lab_client() -> client.ApiClient:
    root = Path(__file__).resolve().parents[2]
    marker = root / ".releasepilot-lab" / "cluster-uid"
    if not marker.is_file():
        raise InspectionError("WRONG_CLUSTER", "lab fingerprint is missing")
    expected_fingerprint = marker.read_text().strip()
    if not expected_fingerprint:
        raise InspectionError("WRONG_CLUSTER", "lab fingerprint is empty")
    try:
        _, active = config.list_kube_config_contexts()
        if not active or active["name"] != CONTEXT_NAME:
            raise InspectionError("WRONG_CONTEXT", "active context is not the ReleasePilot lab")
        config.load_kube_config(context=CONTEXT_NAME)
        api_client = client.ApiClient()
        core = client.CoreV1Api(api_client)
        node = core.read_node("k3d-releasepilot-lab-server-0", _request_timeout=5)
        namespace = core.read_namespace(LAB_NAMESPACE, _request_timeout=5)
        annotation = (namespace.metadata.annotations or {}).get("releasepilot.dev/cluster-uid")
        LabIdentity(CONTEXT_NAME, CLUSTER_NAME, str(node.metadata.uid)).verify(expected_fingerprint)
        if annotation != expected_fingerprint:
            raise InspectionError("WRONG_CLUSTER", "namespace fingerprint mismatch")
    except ConfigException as error:
        raise InspectionError("K8S_CONFIG", "Kubernetes lab context cannot be loaded") from error
    except LabIdentityError as error:
        raise InspectionError("WRONG_CLUSTER", str(error)) from error
    except ApiException as error:
        code = {401: "K8S_UNAUTHENTICATED", 403: "K8S_FORBIDDEN"}.get(
            error.status, "K8S_UNAVAILABLE"
        )
        raise InspectionError(code, f"lab identity read failed with HTTP {error.status}") from error
    except (OSError, HTTPError) as error:
        raise InspectionError("K8S_UNAVAILABLE", "Kubernetes lab API is unreachable") from error
    return api_client


def main() -> int:
    parser = argparse.ArgumentParser(prog="releasepilot")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="read a registered lab workload")
    inspect.add_argument("kind", choices=["status", "pods", "events", "logs", "history"])
    inspect.add_argument("--pod", help="required for events or logs")
    args = parser.parse_args()
    if args.command != "inspect":
        parser.error("unsupported command")
    if args.kind in {"events", "logs"} and not args.pod:
        parser.error("--pod is required for events and logs")
    if args.kind not in {"events", "logs"} and args.pod:
        parser.error("--pod is only valid for events and logs")
    try:
        inspector = local_inspector()
        if args.kind == "status":
            evidence = inspector.status()
        elif args.kind == "pods":
            evidence = inspector.pods()
        elif args.kind == "events":
            evidence = inspector.events(args.pod)
        elif args.kind == "logs":
            evidence = inspector.logs(args.pod)
        else:
            evidence = inspector.history()
    except InspectionError as error:
        print(json.dumps({"ok": False, "error_code": error.code, "message": str(error)}))
        return 1
    print(json.dumps({"ok": True, "evidence": evidence.as_dict()}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
