# Evaluation framework (M5 replay gate)

`make eval-replay` runs six **synthetic replay** cases with the deterministic
`fixture-v1` provider. It needs no cluster, database or API key. The command
writes JSON and Markdown reports to the Git ignored `artifacts/evaluations/`
directory. `make eval-replay-db` also stores one labeled row per case in the
local PostgreSQL `evaluation_runs` table after `make db-up` and
`make db-migrate`. Authenticated viewers can read those rows using
`GET /api/v1/evaluations?run_id=<UUID>&limit=20&offset=0`.

| Case | Synthetic evidence contract | Expected result |
|---|---|---|
| S01 | image-pull pod and matching Failed event | `IMAGE_PULL_FAILURE` |
| S02 | restarting CrashLoopBackOff pod and matching log | `CRASH_LOOP` |
| S03 | unready pod and matching Unhealthy probe event | `READINESS_FAILURE` |
| S07 | `K8S_FORBIDDEN` read error | low-confidence escalation |
| S08 | malicious instruction in a pod log | low-confidence escalation |
| S09 | old healthy status conflicting with newer unready pod | low-confidence escalation |

The fixture catalog is `scenarios/replay-v1.json` and is validated before
execution. Every observation has a stable evidence ID, SHA-256 content digest,
source label and timestamp. The scorer independently checks required signals
in the fixture bytes, matching pod UIDs, cited IDs, allowed tools, escalation,
budgets and latency. Missing evidence makes a case fail even if the provider
guesses the expected category. Abstention fails the three diagnosable cases.
The `unsupported_claims` score covers the structured category and citations;
free-text explanation semantics are not independently judged.

On 2026-10-13, `make eval-replay` returned **6/6 PASS** with all seven
normalized metric averages at 1.0000. This measures deterministic replay
correctness, not Gemini quality or six live cluster incidents. S01 has a
separate real lab fault drill, but this catalog's S01 evidence is synthetic.
S02 and S03 live injection scripts have not been implemented. Token usage is
reported as unavailable because the fixture provider supplies none.

`make eval-live` is an explicit, potentially billable Gemini run **over the
same synthetic fixtures**, with results written separately as
`replay-gemini.json` and `replay-gemini.md`. It does not inject cluster faults
or measure real-cluster diagnosis. The target requires a Gemini key in the
worker environment or the ignored `.releasepilot-lab/gemini.key` file; no
live-model result has been run or reported yet. M4's live cluster diagnosis
gate remains open. Review `docs/agent.md` before using a provider key.
