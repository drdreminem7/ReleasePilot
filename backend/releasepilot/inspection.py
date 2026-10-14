"""Bounded, namespaced reads for one explicitly registered lab Deployment."""

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from kubernetes import client
from kubernetes.client.exceptions import ApiException
from urllib3.exceptions import HTTPError

from releasepilot.lab_identity import LAB_NAMESPACE

MAX_PODS = 20
MAX_EVENTS = 20
MAX_HISTORY = 10
MAX_LOG_BYTES = 8192
MAX_LOG_LINES = 50
TIMEOUT_SECONDS = 5
SECRET_PATTERN = re.compile(r"(?i)\b(token|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+")


class InspectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RegisteredWorkload:
    namespace: str
    name: str
    uid: str

    def __post_init__(self) -> None:
        if self.namespace != LAB_NAMESPACE or self.name != "checkout-api" or not self.uid:
            raise InspectionError(
                "UNREGISTERED_WORKLOAD", "only the registered lab checkout-api is allowed"
            )


@dataclass(frozen=True)
class Evidence:
    source: str
    observed_at: str
    resource_uid: str
    resource_version: str
    data: object
    truncated: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _observed() -> str:
    return datetime.now(UTC).isoformat()


def _sanitize(value: str, max_bytes: int) -> tuple[str, bool]:
    redacted = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    encoded = redacted.encode("utf-8")
    truncated = len(encoded) > max_bytes
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), truncated


class KubernetesInspector:
    """SDK calls remain inside a fixed namespace and a fixed workload selector."""

    def __init__(self, workload: RegisteredWorkload, api_client: client.ApiClient) -> None:
        self.workload = workload
        self.apps = client.AppsV1Api(api_client)
        self.core = client.CoreV1Api(api_client)

    @staticmethod
    def _api_error(error: ApiException) -> InspectionError:
        code = {
            401: "K8S_UNAUTHENTICATED",
            403: "K8S_FORBIDDEN",
            404: "K8S_NOT_FOUND",
            429: "K8S_RATE_LIMITED",
        }.get(error.status, "K8S_UNAVAILABLE")
        return InspectionError(code, f"Kubernetes read failed with HTTP {error.status}")

    def _deployment(self) -> Any:
        try:
            deployment = self.apps.read_namespaced_deployment(
                self.workload.name, self.workload.namespace, _request_timeout=TIMEOUT_SECONDS
            )
        except ApiException as error:
            raise self._api_error(error) from error
        except (OSError, HTTPError) as error:
            raise InspectionError("K8S_UNAVAILABLE", "Kubernetes API is unreachable") from error
        if deployment.metadata.uid != self.workload.uid:
            raise InspectionError("STALE_WORKLOAD_UID", "registered workload UID no longer matches")
        return deployment

    def status(self) -> Evidence:
        deployment = self._deployment()
        conditions = [
            {"type": item.type, "status": item.status, "reason": item.reason}
            for item in (deployment.status.conditions or [])
        ]
        return Evidence(
            source=f"deployment/{self.workload.namespace}/{self.workload.name}",
            observed_at=_observed(),
            resource_uid=self.workload.uid,
            resource_version=str(deployment.metadata.resource_version),
            data={
                "generation": deployment.metadata.generation,
                "observed_generation": deployment.status.observed_generation,
                "desired_replicas": deployment.spec.replicas,
                "ready_replicas": deployment.status.ready_replicas or 0,
                "updated_replicas": deployment.status.updated_replicas or 0,
                "conditions": conditions,
            },
        )

    def _pods(self) -> Any:
        self._deployment()
        try:
            return self.core.list_namespaced_pod(
                self.workload.namespace,
                label_selector="app=checkout-api",
                limit=MAX_PODS,
                _request_timeout=TIMEOUT_SECONDS,
            )
        except ApiException as error:
            raise self._api_error(error) from error
        except (OSError, HTTPError) as error:
            raise InspectionError("K8S_UNAVAILABLE", "Kubernetes API is unreachable") from error

    def pods(self) -> Evidence:
        listing = self._pods()
        items = []
        for pod in listing.items[:MAX_PODS]:
            waiting = [
                status.state.waiting.reason
                for status in (pod.status.container_statuses or [])
                if status.state and status.state.waiting
            ]
            items.append(
                {
                    "name": pod.metadata.name,
                    "uid": pod.metadata.uid,
                    "phase": pod.status.phase,
                    "ready": all(status.ready for status in (pod.status.container_statuses or []))
                    and bool(pod.status.container_statuses),
                    "restart_count": sum(
                        status.restart_count for status in (pod.status.container_statuses or [])
                    ),
                    "waiting_reasons": waiting,
                }
            )
        return Evidence(
            source=f"pods/{self.workload.namespace}/app=checkout-api",
            observed_at=_observed(),
            resource_uid=self.workload.uid,
            resource_version=str(listing.metadata.resource_version),
            data=items,
            truncated=bool(listing.metadata._continue) or len(listing.items) > MAX_PODS,
        )

    def _matched_pod(self, pod_name: str) -> Any:
        if not re.fullmatch(r"checkout-api-[a-z0-9-]{1,55}", pod_name):
            raise InspectionError("INVALID_POD", "pod name is outside the registered workload")
        listing = self._pods()
        for pod in listing.items:
            if pod.metadata.name == pod_name:
                return pod
        raise InspectionError("INVALID_POD", "pod is not in the bounded registered workload set")

    def events(self, pod_name: str) -> Evidence:
        pod = self._matched_pod(pod_name)
        try:
            listing = self.core.list_namespaced_event(
                self.workload.namespace,
                field_selector=f"involvedObject.name={pod_name}",
                limit=MAX_EVENTS,
                _request_timeout=TIMEOUT_SECONDS,
            )
        except ApiException as error:
            raise self._api_error(error) from error
        except (OSError, HTTPError) as error:
            raise InspectionError("K8S_UNAVAILABLE", "Kubernetes API is unreachable") from error
        items = []
        truncated = bool(listing.metadata._continue) or len(listing.items) > MAX_EVENTS
        cutoff = datetime.now(UTC) - timedelta(hours=1)
        for event in listing.items[:MAX_EVENTS]:
            timestamp = event.last_timestamp or event.event_time
            if (
                event.involved_object.uid != pod.metadata.uid
                or timestamp is None
                or timestamp.tzinfo is None
                or timestamp < cutoff
            ):
                continue
            message, cut = _sanitize(event.message or "", 512)
            truncated |= cut
            items.append(
                {
                    "reason": event.reason,
                    "type": event.type,
                    "message": message,
                    "last_timestamp": timestamp.isoformat(),
                    "pod_uid": event.involved_object.uid,
                }
            )
        return Evidence(
            source=f"events/{self.workload.namespace}/{pod_name}",
            observed_at=_observed(),
            resource_uid=str(pod.metadata.uid),
            resource_version=str(listing.metadata.resource_version),
            data=items,
            truncated=truncated,
        )

    def logs(self, pod_name: str) -> Evidence:
        pod = self._matched_pod(pod_name)
        try:
            raw = self.core.read_namespaced_pod_log(
                pod_name,
                self.workload.namespace,
                container="checkout-api",
                tail_lines=MAX_LOG_LINES,
                limit_bytes=MAX_LOG_BYTES,
                since_seconds=3600,
                timestamps=True,
                _request_timeout=TIMEOUT_SECONDS,
            )
        except ApiException as error:
            raise self._api_error(error) from error
        except (OSError, HTTPError) as error:
            raise InspectionError("K8S_UNAVAILABLE", "Kubernetes API is unreachable") from error
        content, truncated = _sanitize(str(raw), MAX_LOG_BYTES)
        return Evidence(
            source=f"logs/{self.workload.namespace}/{pod_name}/checkout-api",
            observed_at=_observed(),
            resource_uid=str(pod.metadata.uid),
            resource_version=str(pod.metadata.resource_version),
            data={"content": content},
            truncated=truncated or len(str(raw).encode("utf-8")) >= MAX_LOG_BYTES,
        )

    def history(self) -> Evidence:
        deployment = self._deployment()
        try:
            listing = self.apps.list_namespaced_replica_set(
                self.workload.namespace,
                label_selector="app=checkout-api",
                limit=MAX_HISTORY,
                _request_timeout=TIMEOUT_SECONDS,
            )
        except ApiException as error:
            raise self._api_error(error) from error
        except (OSError, HTTPError) as error:
            raise InspectionError("K8S_UNAVAILABLE", "Kubernetes API is unreachable") from error
        items = []
        for replica_set in listing.items[:MAX_HISTORY]:
            if not any(
                owner.uid == self.workload.uid
                for owner in (replica_set.metadata.owner_references or [])
            ):
                continue
            items.append(
                {
                    "name": replica_set.metadata.name,
                    "uid": replica_set.metadata.uid,
                    "revision": (replica_set.metadata.annotations or {}).get(
                        "deployment.kubernetes.io/revision"
                    ),
                    "images": [
                        container.image for container in replica_set.spec.template.spec.containers
                    ],
                }
            )
        return Evidence(
            source=f"replicasets/{self.workload.namespace}/app=checkout-api",
            observed_at=_observed(),
            resource_uid=self.workload.uid,
            resource_version=str(listing.metadata.resource_version),
            data={"deployment_generation": deployment.metadata.generation, "revisions": items},
            truncated=bool(listing.metadata._continue) or len(listing.items) > MAX_HISTORY,
        )
