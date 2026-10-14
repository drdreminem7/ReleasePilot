# AGENTS.md — ReleasePilot Repository Instructions for Codex

## Purpose

Build ReleasePilot according to `RELEASEPILOT_BUILD_SPEC.md`. This is a separate portfolio project. Never read, copy or modify the user's existing Operations Agent Platform repository as part of this assignment.

## Start of every execution

1. Read `RELEASEPILOT_BUILD_SPEC.md`, `AGENTS.md`, and `PROGRESS.md` in full.
2. Inspect the existing repository; do not overwrite work without understanding it.
3. Identify the first incomplete milestone and its acceptance criteria.
4. Implement the smallest end-to-end working slice necessary to satisfy that milestone.
5. Test the behavior; honestly identify `PASS`, `FAIL`, and `NOT RUN / BLOCKED`.
6. Update `PROGRESS.md`, then give the user a concise report of changes, actual validation, blockers, and next milestone.

## Non-negotiable rules

- **No mocks masquerading as live behavior.** Real Kubernetes, Prometheus, Argo and LLM claims require verified observations. Mocks/fixtures are allowed in explicitly labeled unit and replay tests.
- **No direct LLM access to mutating tools or arbitrary shells.** Use typed bounded read-only tools for the graph. Mutations require an authenticated human approval, separate validated executor, and limited Kubernetes RBAC. Argo's deterministic AnalysisTemplate may independently abort unhealthy canaries.
- **Never touch any non-ReleasePilot cluster.** Before `kubectl`, Helm, test scenario injection or teardown, assert the expected explicitly named local cluster/context and fingerprint. If in doubt, stop and explain.
- **Never read Kubernetes Secrets into LLM context**, or store token/key material in source, UI, reports, prompts, logs or Git.
- **Fail closed:** unknown namespace, resource identity, action, API permission, provider availability, conflicting evidence, expired proposal, invalid state, or failed verification must not become a success.
- **Do not fabricate tests, metrics, benchmark results, deployment claims, security guarantees or screenshots.** If unavailable, report blockers.
- **Version changes are deliberate:** inspect current official APIs, pin compatible versions, document major decisions in `docs/versions.md` / `docs/decisions/`.
- **No unfinished placeholders:** do not mark any milestone complete on TODO comments, unimplemented handlers, inert UI controls, or static/hardcoded pretend monitoring data.
- **No big-bang implementation:** use milestone gates from M0 to M11; if environment prevents validation, do not silently leap forward as though validated.
- **Respect resource limits:** prefer a minimal local lab and incrementally add services; don't introduce Kafka, microservice sprawl, a service mesh or cloud costs without need.

## Coding practices

- Python: typed signatures, Pydantic validation, readable smaller modules, async boundaries managed consistently, meaningful error codes, pytest unit + integration tests, ruff, and SQLAlchemy/Alembic migrations.
- TypeScript: strict types, typed API client, accessible stateful controls, tests for critical workflows; frontend UI is not the authority for security.
- Kubernetes: least-privilege ServiceAccounts, namespaced RBAC, explicit workloads, resource limits, liveness/readiness probes, documented Helm values and reset scripts.
- Dependencies: lock and commit exact resolved versions; use a single tool per ecosystem where practical.
- Security: sanitize untrusted logs; bound time/output/token budgets; use deterministic action policies; keep credentials out of source control.
- Docs: provide commands that actually work, operational prerequisites, failure modes, and limitations.

## Milestone report format

At the end of each execution, report:

```
Milestone: Mx — <name>
Implemented: <specific working components>
Validated: <commands and observed result; PASS/FAIL/NOT RUN>
Changed files: <key paths>
Blockers/risks: <accurate details>
Next: <single next milestone or blockers to resolve>
```

Update `PROGRESS.md` with the same facts. Do not claim to have committed unless a commit was actually created.
