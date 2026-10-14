.PHONY: doctor setup test test-cluster lint cluster-up cluster-down sample-up sample-smoke sample-mode reader-rbac-up reader-rbac-verify scenario-bad-image scenario-verify-bad-image scenario-reset db-up db-migrate run-api run-worker test-db test-graph-fault eval-replay eval-replay-db eval-live monitoring-up monitoring-smoke monitoring-drill test-monitoring-api argo-up rollout-up rollout-refresh-image argo-drill rollout-reset test-rollout-api user-add register-lab register-rollout

doctor:
	bash scripts/doctor.sh

setup:
	cd backend && uv sync --locked
	cd frontend && npm ci

lint:
	cd backend && .venv/bin/ruff check .
	backend/.venv/bin/ruff check sample-app scripts/traffic.py scripts/extract-argo-crds.py
	cd backend && .venv/bin/mypy releasepilot
	cd frontend && npm run lint

test:
	cd backend && .venv/bin/pytest -q
	cd frontend && npm test
	cd sample-app && ../backend/.venv/bin/pytest -q

test-cluster:
	cd backend && RELEASEPILOT_TEST_LAB=1 .venv/bin/pytest -q tests/integration

db-up:
	bash scripts/postgres-up.sh

db-migrate:
	cd backend && bash ../scripts/with-postgres.sh .venv/bin/alembic upgrade head

run-api:
	cd backend && bash ../scripts/with-postgres.sh .venv/bin/uvicorn releasepilot.api:app --host 127.0.0.1 --port 8000

run-worker:
	cd backend && bash ../scripts/with-postgres.sh bash ../scripts/with-provider.sh .venv/bin/python -m releasepilot.worker

test-db:
	cd backend && bash ../scripts/with-postgres.sh --test .venv/bin/pytest -q tests/db

test-graph-fault:
	bash scripts/test-graph-fault.sh

eval-replay:
	cd backend && .venv/bin/python -m releasepilot.evaluation --provider fixture --output-dir ../artifacts/evaluations

eval-replay-db:
	cd backend && bash ../scripts/with-postgres.sh .venv/bin/python -m releasepilot.evaluation --provider fixture --persist --output-dir ../artifacts/evaluations

eval-live:
	cd backend && bash ../scripts/with-provider.sh .venv/bin/python -m releasepilot.evaluation --provider gemini --confirm-cost --output-dir ../artifacts/evaluations

monitoring-up:
	bash scripts/monitoring-up.sh

monitoring-smoke:
	bash scripts/monitoring-smoke.sh

monitoring-drill:
	bash scripts/monitoring-drill.sh

argo-up:
	bash scripts/argo-up.sh

rollout-up:
	bash scripts/rollout-up.sh

rollout-refresh-image:
	bash scripts/rollout-refresh-image.sh

argo-drill:
	bash scripts/argo-drill.sh

rollout-reset:
	bash scripts/rollout-reset.sh

test-rollout-api:
	bash scripts/test-rollout-api.sh

test-monitoring-api:
	bash scripts/test-monitoring-api.sh

user-add:
	cd backend && bash ../scripts/with-postgres.sh .venv/bin/python -m releasepilot.admin user-add "$(USER)" --role "$(ROLE)"

register-lab:
	cd backend && bash ../scripts/with-postgres.sh .venv/bin/python -m releasepilot.admin register-lab

register-rollout:
	cd backend && bash ../scripts/with-postgres.sh .venv/bin/python -m releasepilot.admin register-rollout

cluster-up:
	bash scripts/cluster-up.sh

cluster-down:
	bash scripts/cluster-down.sh

sample-up:
	bash scripts/sample-up.sh

sample-smoke:
	bash scripts/sample-smoke.sh

sample-mode:
	bash scripts/sample-mode.sh "$(MODE)"

reader-rbac-up:
	bash scripts/reader-rbac-up.sh

reader-rbac-verify:
	bash scripts/reader-rbac-verify.sh

scenario-bad-image:
	bash scripts/scenario-bad-image.sh

scenario-verify-bad-image:
	bash scripts/scenario-verify-bad-image.sh

scenario-reset:
	bash scripts/scenario-reset.sh

