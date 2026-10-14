# Copy/Paste into Codex — ReleasePilot Master Prompt

You are the implementation engineer for **ReleasePilot**, a substantial portfolio project: an agentic Kubernetes release investigation and safety platform. The complete, authoritative specification is `RELEASEPILOT_BUILD_SPEC.md` in this repository; `AGENTS.md` defines the working rules; `PROGRESS.md` tracks actual progress.

**Task:** Implement ReleasePilot from scratch in this repository according to the specification, milestone by milestone **M0 through M11**, including source code, tests, Kubernetes/Helm manifests, CI, documentation, reproducible lab fault scenarios, and a functional operator UI. Do not modify my existing Operations Agent Platform.

**Execution protocol:**

1. Read `RELEASEPILOT_BUILD_SPEC.md`, `AGENTS.md`, and `PROGRESS.md` before editing files. Briefly inspect the environment and repository.
2. Implement the first incomplete milestone. Verify every acceptance criterion with actual commands and record PASS, FAIL or BLOCKED/NOT RUN.
3. Only after a milestone is genuinely verified, update `PROGRESS.md` and move to the next milestone **if environment and safety permit**. Maintain small, coherent changes, don't generate the entire architecture as empty stubs.
4. Use current officially documented, compatible package and API versions, lock them, and record decisions. Prefer straightforward code and deterministic tests over fashionable abstractions.
5. **Never execute cluster mutations against any cluster except the explicit local ReleasePilot lab**, and verify its context and identity before operations. Ask me before any destructive action if safe identity verification cannot be established. Never send cloud or Kubernetes credentials to the LLM.
6. Tool use inside the LangGraph agent must stay read-only and bounded. Any actual Kubernetes mutation must be through a separate narrow-permission executor, server-side policies, authenticated explicit approval, revision/UID freshness checks, audit records, and post-action verification. Argo's native deterministic AnalysisRuns handle automatic canary aborts.
7. Do not fake production integrations, metrics, evaluations, test passes, or frontend functionality. If Docker/Kubernetes or an LLM API key is unavailable, continue with meaningful local/unit work where possible, but call the affected integration gate BLOCKED and explain exactly how I can unblock it.
8. At each milestone, provide a concise report with implemented files, actual commands/test results, limitations and the next milestone. Update `PROGRESS.md` accordingly.

**Start now with M0 (repository and developer contract) and M1 (real local Kubernetes laboratory).** If both gates pass, proceed sequentially as permitted. Focus on working code and tests, not on asking me design questions already answered in the specification.
