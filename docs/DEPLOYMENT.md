# Deployment

## Development (one command)
```bash
cp .env.example .env          # defaults work for local dev
make dev                      # docker compose up -d (postgres+redis) + api + worker
```
- API: http://localhost:8000 (serves the UI at `/`)
- Seed + flagship demo: `make demo` (idempotent; deterministic seed 42)
- Tests: `make test`

## Components
| Component | Dev | Production path |
|---|---|---|
| DB | postgres:16 via compose | managed Postgres |
| Cache/limiter | redis:8 via compose (optional; in-memory fallback) | managed Redis |
| API | uvicorn (1 proc) | containers behind LB, N reps |
| Worker | in-repo process | same container, worker command, N reps |
| Web | served by API (StaticFiles) | CDN/static bucket or same image |
| ML | local artifacts dir | S3-compatible artifact store |

## Docker
- `infra/Dockerfile.api` — python:3.12-slim, installs packages, runs uvicorn/worker.
- `infra/docker-compose.yml` — postgres, redis, api, worker; healthchecks; volumes.

## Commands (Makefile)
`make dev · make api · make worker · make migrate · make seed · make demo · make test ·
make loadtest · make verify` (verify = static checks + tests + headless-chrome UI check)

## Config (env)
See `.env.example`: `PAYTWIN_DATABASE_URL`, `PAYTWIN_REDIS_URL`, `PAYTWIN_SECRET_KEY`,
`PAYTWIN_WEBHOOK_SECRET_<PROVIDER>`, `PAYTWIN_LLM_PROVIDER=none|openai|anthropic`,
`PAYTWIN_LLM_API_KEY`, `PAYTWIN_ENV=development|production`.

## CI/CD
`.github/workflows/ci.yml`: lint (ruff) → typecheck (mypy core) → unit/integration/ML/E2E
pytest → bandit + pip-audit + secret scan → frontend static+headless check → docker build.
