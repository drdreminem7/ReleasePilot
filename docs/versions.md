# Version record

Initial stack checked 2026-10-13; M7 Argo checked 2026-10-14 on macOS arm64.
Exact dependency trees are in lockfiles.

| Component | Pinned version | Basis |
|---|---:|---|
| Python | 3.12.x | Installed 3.12.10; project requires 3.12–3.13 |
| uv | 0.11.7 observed | Local tool; lock generation |
| pytest | 8.4.2 | Installed version; backend dev dependency |
| ruff | 0.16.3 | Installed version; backend dev dependency |
| mypy | 1.20.2 | Installed version; backend dev dependency |
| TypeScript | 7.0.2 | npm registry queried 2026-10-13; lockfile records resolution |
| @types/node | 22.20.5 | npm registry Node 22 line queried 2026-10-13 |
| Node.js | 22.14.0 observed | Local tool; frontend minimum 22 |
| kubectl | 1.32.2 | Observed client; one minor behind lab server |
| k3d | 5.9.0 | Installed and tested against this lab |
| k3s / Kubernetes server | 1.33.13+k3s1 | Pinned in `deploy/k3d/cluster.yaml`; observed from live cluster |
| Docker CLI / daemon | 28.0.4 | Observed running during M1 validation |
| Sample image base | Python 3.12.10 slim bookworm, `sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db` | Resolved by Docker and pinned in Dockerfile |
| Kubernetes Python client | 33.1.0 | Official client matrix pairs major 33 with Kubernetes 1.33; exact transitive versions in `backend/uv.lock` |
| PostgreSQL | 18.6-trixie, pinned image digest in `scripts/postgres-up.sh` | Official Docker image; isolated local DB and test DB |
| FastAPI | 0.143.0 | Current release resolved and locked for M3 |
| Pydantic | 2.14.1 | FastAPI compatible validation; exact lock |
| SQLAlchemy | 2.1.4 | ORM and transaction handling; exact lock |
| Alembic | 1.20.0 | Explicit M3–M5 revisions `feee7cc0e96b`, `c93f8d16e7d6`, `7b4c2f8a91de` |
| psycopg | 3.3.6 | PostgreSQL driver with binary extra |
| Uvicorn | 0.54.0 | Local ASGI server |
| argon2-cffi | 25.1.0 | Local password hashing |
| HTTPX | 0.28.1 | TestClient dependency for M3 integration tests |
| LangGraph | 1.2.15 | M4 typed StateGraph and checkpointed workflow |
| LangGraph PostgreSQL saver | 3.1.3 | M4 async checkpoint persistence; its own checkpoint migrations |
| langchain-google-genai | 4.4.1 | M4 structured Gemini provider integration |
| Gemini model | `gemini-3.8-flash` | Official stable model ID; live call not yet verified without key |
| Prometheus server | 3.15.0, image digest `sha256:efd719c99d83b060d9daefdcf00360461adf279f45ef5391f8d111892118753e` | Official release and pulled Linux arm64 image; pinned in `deploy/monitoring/prometheus.yaml` |
| prometheus-client | 0.26.0 | Official Python package; exact backend/sample resolutions in `uv.lock`, sample image wheel hash in `requirements.txt` |
| Argo Rollouts | 1.10.1 | Official `install.yaml` SHA-256 `149148429a6f8258b789003ffb9bc6698a526d611ecb1b185624217cf51bae7f` for CRDs and `namespace-install.yaml` SHA-256 `4351d54af7aa295b5335ada1ba6d3ee9d93314fa78d72961acb8e38fb5dc9721` for namespaced controller |
| Argo controller image | `quay.io/argoproj/argo-rollouts:v1.10.1@sha256:fbcc4cf0a29da25d86230992b1dfdeadf30b6f1baa74ea7c9c98e3e580769396` | Pulled Linux arm64 digest; pinned in guarded installer |
| PyYAML | 6.0.3 | Direct locked dependency to parse the verified Argo release manifest and extract only CRDs |

Kubernetes 1.33 is chosen to keep the installed 1.32 kubectl within the
supported one-minor client skew. The local lab was tested, but the Kubernetes
1.33 maintenance horizon must be revisited before later deployment milestones.
Helm version remains unselected until M10.

References: [uv lock/sync](https://docs.astral.sh/uv/concepts/projects/sync/),
[TypeScript npm package](https://www.npmjs.com/package/typescript),
[Kubernetes version skew policy](https://kubernetes.io/releases/version-skew-policy/).
Lab sources: [k3d v5.9.0 config](https://k3d.io/v5.9.0/usage/configfile/),
[k3s v1.33.13 release](https://github.com/k3s-io/k3s/releases/tag/v1.33.13%2Bk3s1).
Python SDK source: [official compatibility matrix](https://github.com/kubernetes-client/python#compatibility).
M3 API references: [FastAPI security](https://fastapi.tiangolo.com/tutorial/security/),
[SQLAlchemy sessions](https://docs.sqlalchemy.org/en/21/orm/session_basics.html),
[Alembic migrations](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
[psycopg 3](https://www.psycopg.org/psycopg3/docs/),
[PostgreSQL Docker image](https://hub.docker.com/_/postgres).
M4 references: [LangGraph package](https://pypi.org/project/langgraph/),
[PostgreSQL saver](https://pypi.org/project/langgraph-checkpoint-postgres/),
[async saver setup and strict serialization](https://reference.langchain.com/python/langgraph.checkpoint.postgres),
[Gemini integration](https://pypi.org/project/langchain-google-genai/), and
[Gemini 3.8 Flash model](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash).
M5 adds no package dependency. API readiness resolves the current Alembic
head using [Alembic ScriptDirectory](https://alembic.sqlalchemy.org/en/latest/api/script.html)
instead of embedding a revision string.

M6 monitoring references: [Prometheus 3.15.0 release](https://github.com/prometheus/prometheus/releases/tag/v3.15.0),
[scrape configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/),
[instant vector API](https://prometheus.io/docs/prometheus/latest/querying/api/),
[histogram quantiles](https://prometheus.io/docs/prometheus/latest/querying/functions/#histogram_quantile),
and [prometheus-client 0.26.0](https://pypi.org/project/prometheus-client/0.26.0/).

M7 references: [Argo Rollouts v1.10.1 release and artifact checksums](https://github.com/argoproj/argo-rollouts/releases/tag/v1.10.1),
[namespaced installation and separate CRDs](https://argo-rollouts.readthedocs.io/en/stable/installation/),
[canary replica weighting](https://argoproj.github.io/argo-rollouts/features/canary/),
[inline analysis and arguments](https://argoproj.github.io/argo-rollouts/features/analysis/),
and [Prometheus analysis provider](https://argoproj.github.io/argo-rollouts/analysis/prometheus/).

