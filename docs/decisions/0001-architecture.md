# ADR 0001 — Local lab first

Status: accepted, 2026-10-13.

Build in milestone order. The only cluster target is a dedicated k3d cluster named
`releasepilot-lab`, with a persisted cluster UID fingerprint and exact context guard.
No Kubernetes change may rely on the current context alone. M0 includes only the
identity contract and developer checks; the control plane and agent arrive in later
milestones after the lab gate is observed.

Use uv for Python and npm for TypeScript. Keep separate lockfiles because the
sample app will be a separately built image. The first sample image uses Python's
standard library HTTP server to minimize lab resources; the backend framework
is introduced with the persistent API in M3.

