# Known Limitations (genuine, non-critical)

1. **Neural models not trained here** — FT-Transformer / TabPFN / TimesFM / GNN require
   torch-class deps (multi-GB) unavailable on the build machine. Interfaces exist
   (`ModelBackend`), registry supports them; baselines are measured instead. No claim is made.
2. **Single-node scale only (measured)** — load test covers ~1.2k events/s single worker
   and API p95 <50ms on this laptop. 10K-merchant / billion-event design is documented
   (ARCHITECTURE.md scale path), not benchmarked.
3. **Real PSP connectors are sandbox-ready, not live-verified** — Razorpay connector
   implements the dialect + HMAC verification; no production keys were available, so
   end-to-end verification used the simulator + mock connectors.
4. **Auth is API-key based** (hashed, scoped, RBAC) — SSO/OIDC is future scope.
5. **Analytics on Postgres rollups** — ClickHouse migration path documented, not exercised.
6. **LLM composer default is deterministic** — hosted LLM improves phrasing but the
   grounding/tool/refusal layer is identical; no hosted key was available in the build env.
7. **E2E browser test** uses headless Chrome dump-dom + static checks rather than a full
   Playwright suite (Playwright browser download ~120MB was skipped for disk headroom);
   journey logic is covered by the backend E2E test.
8. **Simulated data only** — every metric in the product is simulator-derived and labeled
   as such in-app (SIMULATION env pill); no real production payments are claimed.
