# PayTwin OS Prototype — Audit & Upgrade Plan

**Audited artifacts:**
- `/Users/akshatkumar/Documents/Codex/2026-08-25/referenced-chatgpt-conversation-this-is-an/outputs/paytwin-os-standalone.html` (266 KB pre-built React bundle)
- `paytwin-os-prototype.zip` → full source: **Next.js 16 + React 19 + vinext/Vite (Cloudflare beta)**, `app/page.tsx` (34 KB, one component per line), `app/globals.css` (31 KB hand-written CSS), Tailwind v4 installed but unused.

**Benchmarked against:** the 174-section engineering blueprint, the Deep Analysis & Upgrade Plan (incl. §13 addendum), and the official Buildathon judging bar.

---

## 1. What You Have Today (exact inventory)

Ten screens, all rendered client-side from **hardcoded constants** — no backend, no persistence, no ML, no live data:

| # | Screen | What it shows | Honesty status |
|---|---|---|---|
| 1 | **Overview** | 4 metric cards (Protected GMV ₹24.8L, Recovered ₹1.84L…), bar-chart "pulse", one P1 incident teaser | 🟡 Static props; "LIVE · LAST SYNC 12s AGO" is frozen text |
| 2 | **Health Map** | Provider table (Razorpay/Stripe/Cashfree/Adyen) + 5 fake city nodes (Mumbai, Bengaluru…) as a "payment fabric" | 🔴 Decorative; city map implies geo-routing you don't do |
| 3 | **Incident War Room** | Single hardcoded incident INC-2481: 4-step timeline, causal-evidence bars (HDFC→UPI collect 0.78) | 🟡 Good narrative; exactly ONE incident can ever exist |
| 4 | **Twin Lab** | Sliders (allocation %, duration) → "incremental recovery" via toy formula `allocation*1640 + mins*182` | 🔴 Linear formula ≠ digital twin; no scenarios, no uncertainty |
| 5 | **Policies** | 2 policy cards + a "BLOCKED BY POLICY" story card + create modal | 🟡 Best storytelling in the app; modal doesn't persist anything |
| 6 | **AI Commander** | Chat with two canned if/else answers keyed on "why" | 🔴 Not an agent; no tools, no citations, no refusals |
| 7 | **Experiments** | A/B cards with fixed treatment/control/lift numbers | 🔴 No experiment engine behind it |
| 8 | **Model Health** | Registry claiming *"LSTM + seasonal baseline", "Heterogeneous GNN", "Causal forest", "Contextual bandit"* | 🔴⚠️ **Highest-risk screen**: claims models that don't exist. Any judge who clicks will find vaporware |
| 9 | **Audit Explorer** | 4 decision records (DEC-409x) with evidence snippets + fake sha256 | 🟡 Right idea; "Export audit bundle" shows a toast, exports nothing |
| 10 | **Integrations** | Connector list w/ states; architecture strip "your data → PayTwin brain → rails" | 🟡 Good framing; Connect buttons only append to local array |

Shell features that already work well: sidebar nav groups, ⌘K palette (fixed list), toasts, mobile hamburger, user footer. Design language: dark navy sidebar + light canvas, indigo/purple accents, Geist fonts, unicode glyphs as icons (⌁ ◉ ✦).

---

## 2. Verdict

> **As a pitch prop: 7/10 — clean, credible, well-written copy.**
> **As a product: 2/10 — every number is a constant, every action is a toast.**

Three existential problems:

1. **The demo can't survive questions.** Click anything twice and you hit a wall: one incident forever, a chatbot with two sentences, a simulator that's a multiplication, a model registry full of fiction.
2. **It contradicts your own blueprint.** The blueprint's §174 demands eight provable behaviors; the prototype demonstrates zero of them end-to-end.
3. **Missing everything that differentiates:** no org/merchant hierarchy (§13.4 switcher), no three-level intelligence anywhere on screen, no money-clock, no Recovery Batch Report, no Audit Dossier export, no chaos console, no compliance predicates, no funnel, no mandates, no MCP.

<a name="3-gap-matrix"></a>
## 3. Gap Matrix — Prototype vs. Plan vs. Judging Bar

Legend: ✅ real · 🟡 mocked but present · ❌ absent

| Capability (source) | Status | Notes |
|---|---|---|
| Multi-merchant org hierarchy + switcher (§13.4) | ❌ | Single workspace "Lighthouse"; zero org concept |
| Three-level intelligence visible (§13) | ❌ | Not surfaced anywhere in UI |
| Live event stream / ticking metrics (blueprint §148) | ❌ | Static arrays; "LIVE" is decorative text |
| Incident queue >1 incident | ❌ | INC-2481 hardcoded in 6 places |
| Real digital twin simulation (§19) | ❌ | Linear arithmetic; no scenario library, no CI bands |
| Policy engine + blocked-action proof (§20, bar item) | 🟡 | Story card exists; nothing is actually evaluated |
| Control-vs-treatment batch report (bar item, G5) | ❌ | Experiments page shows fixed numbers; no downloadable artifact |
| Audit dossier export w/ hash chain (S1, bar item) | 🟡/❌ | Records exist visually; export = toast only |
| Stopping rules visible during execution (G8-adjacent) | ❌ | No budget consumption UI |
| AI agent with citations + refusals (M7/S2) | ❌ | Two canned strings; no tools/evals/MCP |
| Chaos Console / seeded scenarios (P6/G8) | ❌ | Demo depends on hardcoded state |
| Compliance predicates UI (P4/G9) | ❌ | Policies mention "Opt-out respected" only as copy |
| Checkout funnel telemetry (P1) | ❌ | Schema starts at payments |
| Mandate/subscription recovery (P2) | ❌ | Absent |
| Model registry backed by real training runs | ❌ | Fictional labels incl. "Heterogeneous GNN" |
| Connector health heartbeat (§24 capabilities) | 🟡 | Static rows; "Cashfree lag 14m" is a prop |
| Money-clock HUD (GMV at risk ticking) | ❌ | Blueprint centerpiece metric not on screen |
| Keyboard-first ops UX | 🟡 | ⌘K exists but searches a fixed list |

**Bottom line:** the prototype covers ~30% of the blueprint's product surface at mock fidelity and ~0% at functional fidelity.

---

<a name="4-ui-spec"></a>
## 4. UI/UX Overhaul — "Best-in-Market" Specification

### 4.1 Design-system foundations (do these before any page work)

1. **Tokenize everything.** Promote the current ad-hoc values into CSS custom properties / Tailwind theme tokens: `--surface-0/1/2`, `--text-primary/muted/faint`, `--accent-indigo #5969E4`, `--accent-violet #805EE8`, semantic `--risk-red/--warn-amber/--ok-green`, spacing scale (4/8/12/16/24/32/48), radius scale (8/12/16/999). One `tokens.css`; every component consumes tokens only.
2. **Dark mode as first-class citizen.** Payment ops tools live dark. Ship dark default + light toggle; charts and risk colors re-map via tokens.
3. **Replace unicode glyphs (⌁ ◉ ✦ ◫)** with **Lucide icons** (`lucide-react`): consistent stroke, sizes, aria-labels. Instant professionalism lift.
4. **Type & data typography:** Geist stays; add **tabular numerals** for all metrics (`font-variant-numeric: tabular-nums`) so live numbers don't jitter; monospace (Geist Mono) for IDs/hashes/policy code.
5. **Motion system:** one `motion.css` with 3 primitives — fade-slide-in for cards (120ms), count-up hook for money values, pulse-dot for live indicators. Respect `prefers-reduced-motion`.
6. **State completeness:** every data region implements **loading skeleton → content / empty / error-retry** states from day one. Mock tools die because they have no failure states.

### 4.2 App shell upgrades

- **Top bar org/merchant switcher** (§13.4 wireframe): `Nova Commerce ▼` → Organization View + merchant list; selection drives global context (`org_id`/`merchant_id` in URL query so views are shareable).
- **Global command palette that actually searches** incidents, merchants, policies, decisions (client-side index over API data; fuzzy match; recent items).
- **Notification center** replacing bell-toast: grouped by incident severity, unread states.
- **Environment pill**: Production/Test/Simulation — Simulation mode tints the whole shell amber (you're in the twin sandbox) — this single cue prevents all "is this real?" confusion in demos.
- **Live status strip**: WS connection dot, event-ingest lag, model-service latency, last-sync clock ticking.

### 4.3 Page-by-page redesign

**P1 · Command Center (replaces Overview)** — *the money screen.*
- **Money-clock HUD** at top: `₹ at risk right now` counting live from the incident engine, with 80% interval subtext and a sparkline of last 30 min.
- Metric row becomes org/merchant-aware (switcher-driven): Processed GMV, Protected GMV, Recovered (causal, with CI), Autopilot actions, Success rate vs expected band.
- Real-time success-rate chart (actual line vs TimesFM expected band, shaded q10–q90) fed by WebSocket; anomaly windows highlighted.
- **Incident queue table** (not one card): id, cohort, severity, age, ₹ at risk, status chip, owner; row-click → War Room deep-link.
- Three-level intelligence strip: tiny "Network prior → Merchant baseline → Live context" breadcrumb on each metric tooltip ("why this number").
- Recovery opportunities list stays (good pattern) but binds to real decision records with EV values.

**P2 · Health Map (becomes Cohort Matrix)**
- Kill the fake city map. Replace with the industry-standard **issuer × PSP × method heatmap**: rows = issuers (HDFC/SBI/ICICI…), columns = PSPs, cells colored by deviation from merchant baseline, sized by volume. Click cell → filtered payments + "create incident" if none.
- Side rail: top-moving cohorts (EWMA/CUSUM triggers), provider latency p50/p95 sparklines, webhook lag per connector.
- Region filter remains but as honest metadata (from event `network_region`), not fantasy nodes.

**P3 · Incident War Room (the judging centerpiece)**
- Multi-incident tabs + deep-link routes (`/incidents/INC-2481`).
- Header: severity pill, state machine badge (DETECTED→TRIAGING→DIAGNOSED→MITIGATING→MONITORING→RESOLVED per §26), detected-at clock, blast radius, **₹ at-risk counter ticking**.
- Layout in 3 columns:
  - *Left:* live timeline (auto-appending from real events, human notes inline).
  - *Center:* evidence pack — causal candidates as ranked cards (graph score, counterfactual-mask delta, DoWhy refuter results), every claim a clickable citation chip (`evt_…`, `metric_id`) that opens raw evidence drawer.
  - *Right:* Decision panel — candidate actions w/ EV bars (incremental ₹ net of costs), constraints checklist (green ticks / red crosses), **stopping-rule budget bar** ("attempts used 2/3 · budget ₹12k/₹20k · window 14/18 min"), Approve / Execute / Reject buttons gated by role, post-action outcome tracker (success within 30m etc.).
- Footer strip: "Ask Commander about this incident" input pinned.

**P4 · Twin Lab (real simulator front-end)**
- Scenario library picker (seeded, deterministic): Issuer outage, PSP degradation, Checkout regression, Webhook storm, Mandate failure, Agentic-mandate failure, Silent leak.
- Parameter panel (allocation %, duration, eligibility cohort) → calls simulation API → returns **distribution, not a number**: incremental recovery with 80% band, SR trajectory chart treatment-vs-control, cost breakdown, policy-compat verdict.
- **Compare view:** up to 3 policies side-by-side with EV bars and risk flags — this is where §112's "policy simulation before activation" lives.
- Divergence demo card: run scenario for two merchants, show different recommended actions (three-level intelligence made visible).

**P5 · Policies (policy-as-code, governed)**
- Policy list with versions + status (Live/Draft/Archived), diff view between versions.
- Editor: structured form generating typed YAML (§20 schema) + validation errors inline; predicate chips incl. compliance set (`dnd_window_ok`, `within_mandate_window`, `consent_on_file`, `contact_budget_ok`, `agent_authority_verified`).
- **Simulate-before-save:** button runs the draft against historical replay and prints projected incremental GMV, retries, contacts added, violations=0 proof.
- Blocked-actions log (your best story) bound to real policy-engine rejections with the exact failed rule highlighted.

**P6 · AI Commander (real agent console)**
- Streaming responses (SSE) with **inline citation chips** after each claim → click opens the exact evidence object.
- **Tool-call trace panel** (collapsible): shows `get_incident → query_metrics → explain_decision` invocations with latency — proves it's instrumented, not vibes; this is also your MCP tool layer made visible (S2).
- Suggested-question chips bound to golden eval set; include one **refusal demo**: "Retry all failed payments now" → typed refusal citing violated predicate.
- Context header: current incident/merchant scope selector; every answer stamped with model version + confidence + evidence coverage (§118).
- Fallback indicator when running on local model (degraded-mode honesty).

**P7 · Experiments & Recovery Reports**
- Experiment registry bound to real control/treatment runs: allocation, n's, lift with 95% CI, Qini/AUUC chart per uplift experiment (M4).
- **Recovery Batch Report generator** (G5): pick window → renders cohort table, incremental ₹ w/ CI, costs, futile retries suppressed, violations count → Download PDF/MD. *This button alone maps to the track bar verbatim.*
- Insight cards stay but link to underlying decision ids.

**P8 · Model Health (truth serum)**
- Registry rows bind to real trained models from MLflow/model dir: name, version, trained-at, dataset fingerprint, AUROC/Brier/ECE from held-out bench, calibration curve from actual predictions, drift signals from live PSI.
- Rename fictional labels until they exist ("Heterogeneous GNN" → "Graph-propagation RCA scorer" until a GNN is actually trained).
- Shadow/canary/champion status per model + promote/rollback actions (§123 pipeline made clickable).
- Link to MODEL_CARD.md per model.

**P9 · Audit Explorer (tamper-evident for real)**
- Rows from append-only audit table with verified hash-chain indicator; filter by actor/policy/incident/time.
- Detail drawer: full §45 record — feature snapshot ref, policy version, approval identity, outcome, prev-hash.
- Working exports: JSONL + human dossier (S1). Replay button (admin-gated) re-runs decision read-only.

**P10 · Integrations**
- Connector cards show **capabilities matrix** (§24: fetch/retry/link/downtime-feed), webhook heartbeat (last event received Xs ago), signature-verification state.
- Razorpay test-mode connect flow: key entry → verify → backfill picker (§150) → baseline progress bar.

**NEW P11 · Merchants** (org directory): merchant cards w/ SR, GMV, protected ₹, incidents; detail = mini command center; onboarding state machine (Connected → Baseline learning → Calibrated → Recommendations → Autopilot-eligible).

**NEW P12 · Funnel** (when P1 module ships): step-conversion bars, drop-off cohorts, recovery nudges log.

**NEW P13 · Benchmark** (PayTwin-Bench): frozen metrics card rendered as UI + "reproduce" instructions — turns credibility into a page.

### 4.4 Interaction standards
- Optimistic UI only where safe (notes, tags); money/actions always round-trip server truth.
- Every destructive/gated action → confirm modal stating the constraint that permits it.
- Deep-linkable state (page+filters+incident in URL); shareable incident briefs (existing idea) become real permalinks.
- Skeletons sized to real p95 latencies; WS reconnect banner with auto-resubscribe.

### 4.5 Accessibility & polish gate
Keyboard map (g+i incidents, g+p policies…), visible focus rings, contrast ≥ 4.5:1 for risk colors on dark, aria-live for toasts/counters, reduced-motion respected, empty states written with personality ("No incidents. Enjoy it — we're still watching.").

<a name="5-real"></a>
## 5. From Mock to Machine — Making It Actually Work

### 5.1 Target architecture (runs on one laptop via Docker Compose)

```text
┌───────────────────────────── Next.js 16 (existing shell) ───────────────────────────┐
│ pages per §4.3 · REST for queries/mutations · WebSocket for live topics             │
└───────────┬──────────────────────────────────────────────┬──────────────────────────┘
            │ REST/WS                                      │ SSE (agent streaming)
┌───────────▼──────────────┐   ┌───────────────────────┐   ┌────────────────────────┐
│ API service (FastAPI)    │   │ Sim Engine (worker)   │   │ Agent Service          │
│ auth · tenants/orgs      │   │ seeded event          │   │ tool layer = same      │
│ incidents · decisions    │   │ generator + incident  │   │ REST APIs; citations   │
│ policies · audit · WS hub│   │ injection; replayable │   │ enforced; LLM w/local  │
└──────┬───────────┬───────┘   └──────────┬────────────┘   │ fallback               │
       │           │                      │ events         └────────────────────────┘
┌──────▼────┐ ┌────▼─────────┐  ┌─────────▼────────┐  ┌─────────────────────────────┐
│ PostgreSQL│ │ DuckDB       │  │ In-proc EventBus │  │ ML Service (FastAPI)        │
│ entities, │ │ Parquet lake │  │ (topics mirror   │  │ success model (XGB/TabPFN)  │
│ decisions,│ │ analytics    │  │ blueprint §9.1)  │  │ TimesFM bands · graph RCA   │
│ actions,  │ └──────────────┘  └──────────────────┘  │ uplift T-learner · conformal│
│ audit hash│                                          └─────────────────────────────┘
└───────────┘        Optional profile: Redpanda · Razorpay test-mode connector
```

Keep the existing Next.js UI — it's good bones. Add one FastAPI monorepo backend instead of microservices (blueprint §166 agrees).

### 5.2 Core data model (Postgres DDL sketch)

```sql
organizations(id, name, created_at)
merchants(id, org_id→organizations, name, config_json, cost_json,
          onboarding_state, baseline_ref, embedding_json)
events(id, merchant_id, type, occurred_at, payload_json, dedupe_key UNIQUE)
metric_windows(merchant_id, cohort_key, window_start, sr, volume, latency_p95)
incidents(id, merchant_id, cohort_key, severity, state, detected_at,
          resolved_at, gmv_at_risk_minor, evidence_json)
decisions(id, incident_id, candidates_json, chosen_action, ev_breakdown_json,
          policy_version, model_versions, propensity, actor, decided_at)
actions(id, decision_id, idempotency_key UNIQUE, state, executed_at, result)
outcomes(action_id, window, recovered bool, amount_minor, attributed_at)
experiments(id, merchant_id, hypothesis, arm_split, started_at, status, results_json)
policies(id, merchant_id, version, yaml_text, status, created_by)
audit_chain(seq, ts, actor_type, actor_id, action, object_id,
            payload_hash, prev_hash)   -- append-only, verified in UI
```

### 5.3 Event pipeline (the heartbeat)

Sim engine (seeded, deterministic) emits canonical events at ~50–200 eps into `payment.canonical.v1`; ingestion validates → writes Postgres+Parquet → rolling feature windows → detectors (EWMA/CUSUM/robust-z vs **merchant baseline** from Level-2 store) → incident builder (dedupes, correlates cohorts via graph-propagation scoring) → decision engine (EV over candidate actions using uplift model + merchant costs) → policy predicates → action executor (simulator connector; optional Razorpay test-mode) → outcome tracker with attribution windows (§C6). Everything replayable by seed.

### 5.4 ML service (real models, honest labels)

- `POST /predict/success` — XGBoost champion + TabPFN challenger, isotonic-calibrated, conformal set width included.
- `POST /forecast/cohort` — TimesFM quantiles (cached per cohort/window).
- `POST /rca/rank` — graph-propagation scores + counterfactual-mask deltas.
- `POST /uplift/score` — T-learner τ(x) per action.
- Training CLI (`make train`) on generator data → saves models + metrics JSON consumed by Model Health page and EVALUATION.md. No fictional labels anywhere.

### 5.5 Decision & execution (the safety story, executable)

```python
# decision_engine.py (essence)
candidates = [NO_ACTION, RETRY, ALTERNATE_METHOD_PROMPT, PAYMENT_LINK, ESCALATE]
for a in candidates:
    tau   = ml.uplift(context, a)                 # P(incremental success)
    ev    = tau * value * clv_mult - costs(a) - friction(contact_n)**gamma
    check = policy.evaluate(a, context)           # typed predicates incl. compliance set
    if not check.allowed: results.append(Blocked(a, check.failed_rule)); continue
results.decide(argmax EV among allowed)
executor.execute(action, idempotency_key=sha256(merchant+payment+action+cycle))
```

Blocked candidates are **stored and displayed** (Policies page blocked-log, War Room red panel). Stopping rules = counters enforced in executor (`max_attempts`, budget minor-units, time window); UI reads them live.

### 5.6 Agent service (Commander for real)

Same REST APIs become the tool layer: `get_incident, list_incidents, query_metrics, explain_decision, run_simulation, propose_action` (write-intent → approval queue only). LLM receives a structured evidence pack; every claim must carry a citation id that the API verifies before render (unverifiable ⇒ stripped). Structured output via Pydantic. Provider-agnostic client with local fallback (Ollama/vLLM small model) — degraded mode is a feature badge, not a failure. Ship `paytwin-mcp` server wrapping the same tools (S2) so Claude Desktop can operate PayTwin on camera.

### 5.7 Real-time contract

WebSocket topics mirror blueprint §9.1 exactly:
`incident.created|updated · anomaly.raised · decision.proposed · action.executed · outcome.recorded · metric.window`
Front-end subscribes per route; money-clock and charts are pure subscribers. This symmetry ("UI topics = future Kafka topics") is a one-line pitch point.

### 5.8 Repo structure (monorepo)

```text
paytwin/
├── apps/web/                  # existing Next.js app, refactored per §4
├── services/api/              # FastAPI: auth, orgs, incidents, decisions, policies, audit, WS hub
├── services/sim/              # seeded generator + incident injector + replay CLI
├── services/ml/               # training CLIs + inference FastAPI + model registry files
├── packages/contracts/        # shared Pydantic/zod schemas (canonical event, decisions)
├── evals/                     # golden_questions.yaml, bench runner, metrics_card.json
├── infra/docker-compose.yml   # web, api, sim, ml, postgres  (+ profile: redpanda)
└── docs/                      # ARCHITECTURE / MODEL_CARD / THREAT_MODEL / EVALUATION
```

### 5.9 Minimum-viable security (even pre-production)

Env-based secrets only; webhook HMAC verification in connector; tenant scoping middleware on every query (org_id/merchant_id derived from session, never body); role gates (`viewer/operator/approver/admin`) enforced server-side; append-only audit writes with hash chain; rate-limit agent write intents to approval queue.

<a name="6-sequence"></a>
## 6. Build Sequence — Prototype → Working Product

**Phase A · Spine (Week 1)** — *make data real*
Contracts package + Postgres DDL + sim engine emitting canonical events + ingestion + rolling windows + WS hub. UI: shell tokens/dark-mode/icons swap; Command Center binds to live metrics; org/merchant switcher over seeded org (Nova Commerce × 4 merchants). **DoD:** refresh page mid-stream → numbers keep moving from events, not constants.

**Phase B · Intelligence (Week 2)** — *make brains real*
Detectors vs merchant baseline → incident builder → War Room live timeline + evidence pack. ML service: train success model + TimesFM bands + graph RCA on generator data; Cohort Matrix heatmap bound to metric_windows. Twin Lab calls simulation API w/ CI bands + scenario library. **DoD:** press "inject PSP degradation" in Chaos panel → incident appears ≤60s with ranked RCA.

**Phase C · Governed action (Week 3)** — *make the bar provable*
Policy engine w/ predicate set + EV decision engine + idempotent executor + outcome tracker + stopping-rule counters. Policies page (editor/simulate-before-save/blocked-log). Experiments page → Recovery Batch Report export. Audit chain writes everywhere. **DoD:** full loop detect→diagnose→simulate→decide→block-or-execute→measure, all persisted, batch report downloads.

**Phase D · Agent & polish (Week 4)** — *make it demo-ready*
Agent service + citations + refusal + MCP server; Model Health bound to real registry; Audit dossier export; Benchmarks page from `metrics_card.json`; a11y/keyboard pass; empty/error states; record video per beat sheet (Deep-Analysis §8). **DoD:** Claude Desktop answers an incident question citing evidence ids; every §174 proof demonstrable in <5 min.

<a name="7-quickwins"></a>
## 7. Quick Wins (do today, ~1 day total)

1. Delete/replace fictional model labels on Model Health until trained ("coming in v0.2" chips are fine — fiction is not).
2. Wire "Export audit bundle" + "Share brief" to generate real files client-side (Blob download) even before backend.
3. Make ⌘K palette search the actual nav + incidents list (local array is fine for now).
4. Add tabular numerals + count-up animation on money values; fix frozen "LAST SYNC" clock to tick.
5. Lucide icon swap; dark-mode toggle via token inversion.
6. Loading skeletons + empty states on all ten pages.
7. Rename "Lighthouse" workspace → `Nova Commerce` org with 4 merchants in sidebar (static first, wired later).
8. Favicon/meta/OG tags + README screenshots of current UI.

<a name="8-risks"></a>
## 8. Risks & Notes

| Risk | Mitigation |
|---|---|
| Scope explosion (13 pages × real backends) | Phases gate everything; pages degrade gracefully to read-only until their phase lands |
| TimesFM/TabPFN weights heavy for judges' laptops | Vendor models in release assets; CPU fallbacks documented |
| Sim realism challenged | Publish generator assumptions next to Bench page (blueprint §121/§163 stance) |
| Agent flakiness on camera | Local-fallback model + scripted golden questions; pre-rendered backup take |
| vinext beta toolchain risk | It's Cloudflare's bundler path; if blocked, plain Vite or Next dev server works unchanged for UI work |
| Two sources of truth (mock vs API) during migration | Phase A forbids new hardcoded numbers; every component gets `data-from="api|mock"` tag until migrated |

---

## Closing

The prototype already looks like a product; now make it behave like one. The order matters: **spine → brains → governance → agent**, because each phase turns one page from theater into truth while keeping the demo runnable every single day. The judging bar ("measured money recovered across a batch, compliant escalation, stopping rules, audit trail") maps 1:1 onto Phase C — nothing else needs to exist before that does.
