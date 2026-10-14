# Investigation graph (M4 in progress)

The worker uses a typed LangGraph `StateGraph` with separate workload
validation, initial snapshot, bounded tool selection, read-only tool
execution, evidence analysis, structured diagnosis, citation/policy check and
final report nodes. The only callable tools in this phase are workload status,
matched pods, matched pod events/logs, and release history. Prometheus and
Argo tools await their milestones. There is no Kubernetes mutation tool.

The graph allows two rounds and five reads, with an overall 45 second budget.
M2's per-read timeout, item limits and log redaction remain in force. The
Gemini prompt has a 20,000 character input cap and withholds log content and
untrusted Kubernetes event messages from the external provider; event reason,
type, time and evidence ID remain available. Diagnosis may recommend only `none`,
`investigate_more` or `escalate`; nonexistent evidence IDs and unsupported
non-abstaining claims fail. A healthy claim must cite complete Deployment and
pod observations that are both ready. An image-pull claim must cite a pod with
`ErrImagePull` or `ImagePullBackOff`; a crash loop alone cannot support it.
Checkpoints use PostgreSQL's official async saver
with a strict serializer allowlist and a stable investigation thread ID.
Domain evidence and reports are separate from checkpoint tables.
The worker records each completed graph node in investigation events. If the
domain report transaction fails after the graph finishes, the worker leaves
the investigation `RUNNING`; a restarted worker projects the completed
checkpoint without another Kubernetes read or provider call.

The default provider uses `gemini-3.8-flash` via `langchain-google-genai`.
Set `GEMINI_API_KEY` in the worker process environment to enable live calls;
no key is needed for ordinary tests. A missing key becomes a durable
`PROVIDER_UNAVAILABLE` escalation. Never put the key in source, manifests,
shell history or reports. For local `make run-worker`, the optional ignored
`.releasepilot-lab/gemini.key` file can contain only the key on one line and
must have mode 0600; `scripts/with-provider.sh` loads it without printing it.
The explicit `RELEASEPILOT_PROVIDER=fixture` mode
uses deterministic classification for tests and replay; its results must not
be described as live-model performance.

With the healthy lab and isolated database ready, run `make test-db` for real
Kubernetes reads, PostgreSQL evidence persistence, crash/restart checkpoint
recovery and missing-key refusal. Run `make test-graph-fault` to inject the
guarded bad-image failure, verify real pod/event evidence, run the fixture
diagnosis, and reset the lab even if the test fails. The graph's provider,
policy and budget unit tests run in `make test` without a cluster.

Current M4 gate: the fixture path has passed real lab tests. A live Gemini
diagnosis has not run because no API key is present. The graph also has no
approval/action branch or `interrupt`/`Command` approval-resume test yet; that
boundary is M8, and no action is executable from this graph. The §5
pause/resume requirement remains open until that integration is tested.
