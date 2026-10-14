# ADR 0003: checkpointed read-only graph and separate domain projection

Date: 2026-10-13. Status: accepted for M4 local work; live provider gate open.

LangGraph owns investigation continuation state, using its PostgreSQL async
checkpoint saver and a stable UUID thread ID stored on the investigation. The
saver's own `checkpoint_*` tables remain separate from Alembic managed domain
tables. The saver uses an explicit strict Msgpack allowlist.

Every graph tool name is code-defined and dispatches only to the M2 read
adapter. Two rounds, five tool calls and a 45 second wall budget cap an
investigation. Log content is withheld from the external model prompt even
after M2 redaction. Diagnosis is schema validated, and citations must match
the recorded evidence IDs. No action tool or Kubernetes writer exists in the
graph. The fixture provider is explicitly labeled and cannot be counted as
live Gemini quality.

The graph emits bounded node progress events. On completion, the worker
stores evidence rows, a structured report, a terminal event and an audit row
in one domain transaction. If that projection fails, the investigation stays
`RUNNING`; a worker restart loads the completed checkpoint and retries the
projection without rereading the cluster or calling the provider. A
PostgreSQL advisory lock prevents simultaneous workers from processing the
same investigation. A process kill after a partial checkpoint was tested.

Tradeoffs: the live Gemini path needs a user-provided API key and has not been
run here. The local worker still uses the developer kubeconfig for read-only
SDK calls; deployment under a limited ServiceAccount is a later milestone.
Prometheus and Argo evidence tools await M6/M7, and approval/action paths
await M8.
