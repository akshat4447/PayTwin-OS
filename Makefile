# PayTwin OS — developer entrypoints (fresh machine: see README.md quickstart)
VENV = ./.venv/bin
PY = $(VENV)/python

.PHONY: help setup dev api worker migrate seed demo razorpay-demo razorpay-api test loadtest verify clean

help:
	@echo "make setup     - create venv + editable installs"
	@echo "make dev       - postgres/redis up + migrate + api on :8000"
	@echo "make api       - run API only (sqlite)"
	@echo "make worker    - run detection/autopilot worker loop"
	@echo "make migrate   - alembic upgrade head"
	@echo "make seed      - seed demo world (org/merchants/keys/policies)"
	@echo "make demo      - full flagship demo (history+outage+detect+act+story)"
	@echo "make razorpay-demo - fresh sandbox Razorpay Test Mode demo + verification"
	@echo "make razorpay-api  - serve the sandbox Razorpay demo database"
	@echo "make test      - pytest suite"
	@echo "make loadtest  - webhook flood + API latency percentiles"
	@echo "make verify    - audit chain verification against the demo DB"

setup:
	python3 -m venv .venv
	$(VENV)/pip install --upgrade pip
	$(VENV)/pip install -e packages/contracts -e services/sim -e services/ml -e services/api
	$(VENV)/pip install httpx pytest bandit pip-audit

dev:
	cd infra && docker compose up -d postgres redis
	PAYTWIN_DATABASE_URL=postgresql+psycopg://paytwin:paytwin_dev@localhost:5433/paytwin $(MAKE) migrate
	PAYTWIN_DATABASE_URL=postgresql+psycopg://paytwin:paytwin_dev@localhost:5433/paytwin $(VENV)/uvicorn paytwin_api.main:app --reload --port 8000

api:
	PAYTWIN_DATABASE_URL=$${PAYTWIN_DATABASE_URL:-sqlite:///./data/dev.db} \
		$(VENV)/uvicorn paytwin_api.main:app --reload --port 8000

worker:
	$(PY) -m paytwin_api.worker

migrate:
	PAYTWIN_DATABASE_URL=$${PAYTWIN_DATABASE_URL:-sqlite:///$(CURDIR)/data/dev.db} \
		/bin/sh -c 'cd services/api && ../../.venv/bin/alembic upgrade head'

seed:
	PAYTWIN_DATABASE_URL=$${PAYTWIN_DATABASE_URL:-sqlite:///./data/demo.db} \
		$(PY) -c "import sys; sys.path.insert(0,'services/sim'); from paytwin_sim.demo import seed_world, make_db; print(seed_world(make_db()))"

demo:
	PAYTWIN_DEMO_RESET=$${PAYTWIN_DEMO_RESET:-0} PAYTWIN_SEED=$${PAYTWIN_SEED:-42} \
	PAYTWIN_DATABASE_URL=$${PAYTWIN_DEMO_URL:-sqlite:///$(CURDIR)/data/demo.db} \
		$(PY) -m paytwin_sim.demo
	@echo "DEMO_RUN.md written. Open http://localhost:8000/?key=<risk_admin key printed above>"

razorpay-demo:
	PAYTWIN_DEMO_RESET=1 PAYTWIN_DEMO_HOURS=$${PAYTWIN_DEMO_HOURS:-1.5} PAYTWIN_SEED=$${PAYTWIN_SEED:-42} \
	PAYTWIN_DATABASE_URL=$${PAYTWIN_RAZORPAY_DEMO_URL:-sqlite:///$(CURDIR)/data/razorpay-hackathon.db} \
		$(PY) scripts/razorpay_demo.py
	@echo "RAZORPAY_TEST_MODE_DEMO.md written. Start 'make razorpay-api' and use the risk_admin key printed above."

razorpay-api:
	PAYTWIN_DATABASE_URL=$${PAYTWIN_RAZORPAY_DEMO_URL:-sqlite:///$(CURDIR)/data/razorpay-hackathon.db} \
		$(VENV)/uvicorn paytwin_api.main:app --reload --port 8000

test:
	PAYTWIN_DATABASE_URL=sqlite:///./data/test.db $(PY) -m pytest tests/ -q

loadtest:
	PAYTWIN_DATABASE_URL=sqlite:///./data/loadtest.db $(PY) scripts/loadtest.py

verify:
	PAYTWIN_DATABASE_URL=$${PAYTWIN_DEMO_URL:-sqlite:///$(CURDIR)/data/demo.db} \
		$(PY) scripts/verify_audit.py

clean:
	rm -rf .pytest_cache **/__pycache__ data/*.db
