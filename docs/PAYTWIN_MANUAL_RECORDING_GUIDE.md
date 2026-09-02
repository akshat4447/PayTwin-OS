# PayTwin OS — manual recording runbook

Companion to [`PAYTWIN_5_MINUTE_RECORDING_MASTER_PLAN.md`](PAYTWIN_5_MINUTE_RECORDING_MASTER_PLAN.md).
That file is the source of truth for narration, Figma treatment and editorial
rules — read it once first. This file is the physical, step-by-step
walkthrough for **you, operating your own mouse and screen recorder**, clip
by clip, with exact clicks, exact text to wait for, and exact hold times.

All eleven live-product money figures below were re-verified against a fresh
`PAYTWIN_DEMO_RESET=1 PAYTWIN_SEED=42` run on 2026-09-02 and matched the
master plan byte-for-byte (58 treatment / 62 control, ₹25,200 gross,
₹16,556.13 incremental gross, ₹20.30 cost, ₹16,535.83 net, 95% interval
₹8,676.93–₹24,394.73). Every button label and "wait for" string referenced
below exists verbatim in the current `apps/web/index.html`. Nothing here is
guessed.

---

## 0. Read this before you press record

### 0.1 Your environment is already up

A PayTwin API server has been running for you on `http://127.0.0.1:8011`
against `data/recording.db` — this is the exact URL the master plan targets.
Don't start a second server on that port; it'll just fail to bind and you'll
end up talking to the same process anyway. Confirm it's alive:

```bash
curl -s http://127.0.0.1:8011/api/health
```

You should see `{"status":"ok","db":true,...}`. If it's not running, bring it
up against that same database so you don't lose whatever incident/experiment
history is already seeded there:

```bash
PAYTWIN_DATABASE_URL=sqlite:///$(pwd)/data/recording.db \
  ./.venv/bin/uvicorn paytwin_api.main:app --port 8011
```

**Session freshness matters.** The workspace-session cookie your browser is
holding is only valid for 8 hours from when you first entered the key
(`workspace_session_ttl_seconds` in `config.py`). If that server has been up
a while, your session may be close to expiring. Before you start capturing,
open `http://127.0.0.1:8011/#key=<your risk_admin key>` once in the tab
you'll record from — this re-establishes a fresh 8-hour session and scrubs
the key back out of the URL automatically. If you don't have that key handy,
check wherever you saved it when you first seeded `recording.db` (it's
printed once to stdout at seed time and never stored in recoverable form —
if it's truly lost, re-seed with `PAYTWIN_DEMO_RESET=1 PAYTWIN_SEED=42
PAYTWIN_DEMO_URL=sqlite:///$(pwd)/data/recording.db make demo`, which is
fully deterministic and will reproduce the exact same INC-2481 / recovery
batch story).

### 0.2 The one thing that can ruin a retake

Almost everything in this flow is safe to click over and over — forecasts,
twin simulations, policy replays, audit verification, and the Reliability
Lab's fixture checks are all either read-only or run against an isolated
in-memory model that never touches merchant data (the UI says so directly:
*"Isolated proof fixtures never alter this workspace gate"*).

**One button is not safe to repeat: `Introduce scenario events` in Scenario
Lab (clip 02).** It calls a real chaos-injection endpoint
(`POST /api/chaos/surge_bank_failure`) that adds genuine synthetic events to
the live database. It targets the same cohort as INC-2481 (issuer HDFC ×
method upi_intent), so a second click won't open a *different* incident, but
it will grow the affected-payment count and RaR numbers on screen a little
more each time — meaning if you click it three times while rehearsing, the
numbers you see in clip 03 (War Room) will be visibly bigger than what's in
this guide.

**Rule: rehearse clip 02 up to and including hovering over `Introduce
scenario events`, but do not click it until the take you intend to keep.**
Everything before and after that one click can be freely retaken.

The local Razorpay lifecycle (clip 06 — create order → capture → verify →
fulfil) is safe to repeat too: each run creates a brand-new order, so retakes
just add more historical orders rather than corrupting anything.

### 0.3 Recording tool setup (macOS)

- **QuickTime Player** → File → New Screen Recording → click the dropdown
  next to the record button → Options: no microphone, show mouse clicks off
  (you don't want the click-ripple overlay in a professional recording).
  Drag a fixed capture region matching your browser window rather than
  capturing the full display — this makes cropping browser chrome in editing
  much less finicky. Or use **OBS** with a Window Capture source locked to
  the browser window if you want built-in 1920×1080/30fps output without a
  later re-encode.
- Target 1920×1080 at 30fps. If your display is Retina/scaled, either record
  at native resolution and downscale in editing, or set the browser window to
  exactly 1920×1080 first (resize the window, then check
  `window.innerWidth`/`innerHeight` in a throwaway console tab before you
  start — don't leave DevTools open during actual capture).
- Quit Slack, Mail, Calendar, and anything else that can pop a notification
  banner. Turn on Do Not Disturb.
- Light theme, 100% browser zoom, one tab, no bookmarks bar, no extensions
  visible, page scrolled to top before every clip starts.
- Do one **five-second throwaway recording** first: move the mouse from
  center-screen to the `Start operational flow` button and hover without
  clicking, then stop and play it back. Confirm the cursor is actually
  visible in the capture (some capture methods hide it) and that nothing
  else — notification, another window, a password-manager bubble — appears.
  If the cursor isn't visible, that's fine, just record all real clips the
  same way and add one consistent cursor overlay later in editing; don't mix
  visible-cursor and invisible-cursor clips.

### 0.4 Recording strategy: eleven separate files, not one continuous take

Record each clip below as its **own separate file**, named exactly as shown.
Don't try to capture the whole five minutes in one unbroken take — if you
fumble a click in clip 08, you don't want to have to redo clips 01–07 to get
a clean run. Because clip 02 is the only truly single-shot action, doing
clips as separate files costs you nothing and buys you cheap retakes on
everything else.

Give every clip **1.5 seconds of stable pre-roll** (don't click or move the
mouse for the first 1.5s) and a **2-second stable tail** at the end, so the
editor has room to make clean cuts and match-cuts against the Figma
transitions.

---

## 1. The eleven clips, in recording order

Timestamps below are where each clip lands in the final 5:00 edit (per the
master plan's timeline) — they tell you how long the *edited* segment will
be, not how long to record. Record generously (the "raw target length" row);
the editor trims to the "edited use" length.

### Clip 01 — `01_command_center_to_scenario_lab.mp4` (edit: 00:27–00:47, ~22s)

1. Navigate to `http://127.0.0.1:8011/#overview`.
2. Confirm the top bar reads **`LOCAL WORKSPACE · CONNECTED`**, no modal is
   open, page is scrolled to top.
3. Hold still for 2 seconds on the organization name, GMV-at-risk figure,
   success rate, and active-incident count — this is your "problem taste"
   establishing shot.
4. Move the cursor to the **`Start operational flow`** button, hover 0.5s,
   click once.
5. Wait for the Scenario Lab page to fully render and the
   **`Pre-incident scenario forecast`** heading to appear. Hold 1.5s.
6. Stop.

*Narration that will sit over this (read `PAYTWIN_5_MINUTE_RECORDING_MASTER_PLAN.md` §5 for the full script — you don't speak this live, it's dubbed later):* "This is PayTwin OS, an AI revenue-recovery control plane… I'll start a flash-sale plus issuer-failure scenario…"

### Clip 02 — `02_forecast_inject_compare.mp4` (edit: 00:47–01:14, ~30s) — ⚠ single-shot

1. Continue from Scenario Lab (same frame clip 01 ended on).
2. Hold 2s on the scenario name, the 80% risk range, and the bounded-response
   line.
3. Click **`Introduce scenario events`**. *(This is the one non-repeatable
   click — see §0.2. Make sure you're actually ready to keep this take.)*
4. Wait for the toast **`Scenario events introduced`**. Let the page settle
   (don't scroll or click during the ~1–2s data refresh).
5. Click **`Compare response options`**.
6. Wait until the decision comparison renders, then scroll down slowly
   **once** to reveal the recommended / review / blocked policy cards.
7. Scroll back up to the guided-flow action area and click
   **`Open incident evidence`**.
8. Wait for the Incident War Room to render fully, incident **INC-2481**
   visible. Hold 1.5s.
9. Stop.

### Clip 03 — `03_war_room_evidence_and_rollback.mp4` (edit: 01:14–01:38, ~25s)

1. Confirm the selected incident is **INC-2481** (if it isn't the one shown,
   select it explicitly from the incident list rather than assuming it's
   featured by default).
2. Hold 1.5s on the incident title and its presentation/state chip.
3. Move the cursor slowly, in this order, pausing ~1s at each: incident ID →
   causal evidence panel → the policy-allowed candidate → the blocked
   full-reroute candidate → the stopping-rules panel.
4. If a rollback banner is present anywhere on the page, hold on it for a
   full 2 seconds.
5. **Do not click `Mark resolved` or `Halt autopilot`** — these are
   real state-changing controls and not part of the film.
6. Click **`Ask Commander`**.
7. Wait for the Commander page to render and settle. Hold 1s.
8. Stop.

### Clip 04 — `04_commander_explain_and_refuse.mp4` (edit: 01:50–02:14, ~20s)

1. Continue from Commander (or navigate to it fresh with INC-2481 still the
   selected incident/scope).
2. Click **`Why this action?`** once.
3. Wait for the **complete** answer and its read-only tool trace to finish
   rendering — do not cut mid-stream.
4. Click **`Retry everything now`** once.
5. Wait for the refusal message — it should cite something like
   `max_attempts` or `dnd_window_ok` (policy-blocked evidence). Hold 2s on
   the refusal.
6. Click **`Policies`** in the left sidebar and let the page settle.
7. Stop.

### Clip 05 — `05_typed_policies_and_block.mp4` (edit: 02:21–02:39, ~17s)

1. Continue on the Policies page.
2. Hold 1.5s on the active-policy banner and the blocked-request count.
3. Click the first **`View YAML`**. Hold the rendered typed rules for 1.5s
   (this now shows real `rules:` content from the API, not a placeholder —
   confirm you don't see the literal text `(typed rules from API)`).
4. Close the modal.
5. Scroll down to **`Rehearse before you save`**.
6. Click **`Run historical replay`**.
7. Wait for the toast **`Historical replay complete`**. Keep the deliberately
   blocked request visible on screen for at least 2 seconds somewhere in this
   clip.
8. Click **`Integrations`** in the sidebar and let it settle.
9. Stop.

### Clip 06 — `06_local_razorpay_lifecycle.mp4` (edit: 02:45–03:10, ~26s)

1. Continue on Integrations. Confirm all four lifecycle cards render
   (Create order / Capture / Verify / Record fulfilment).
2. Click **`Create order`**. Wait for the order ID to appear and the capture
   button to enable.
3. Click **`Capture local payment`**. Wait for **`verified + materialized`**
   and for Checkout verification to enable.
4. Click **`Verify Checkout`**. Wait for the verified state.
5. Click **`Record fulfilment`**. Wait for the exact text
   **`Fulfilment recorded exactly once.`**
6. Hold the final receipt state for 2 seconds.
7. **Skip refund** in this take — it's an optional extra clip, not part of
   the five-minute cut.
8. Click **`Reliability Lab`** in the sidebar and let it settle.
9. Stop.

### Clip 07 — `07_reliability_break_fix_forge.mp4` (edit: 03:10–03:50, ~36s)

1. Continue on Reliability Lab, in the **Guided Control Proof** section
   (not a generic suite row).
2. Click **`Run control check`**.
3. Wait for **`Duplicate fulfilment control caught`** and the
   **`FIXTURE BLOCKED`** state. Hold 2s.
4. Click **`Verify corrected handler`**.
5. Wait for **`Correction verified`** and **`ONE FULFILMENT VERIFIED`**.
   Hold 2s.
6. Scroll to **`Webhook Lab · fault injection`**.
7. Click **`Forged signature`**.
8. Wait until **`Forged signature rejected`** and the zero-side-effects
   confirmation are both visible. Hold to the end of that state.
9. After a 2-second tail, click **`Experiments & Recovery`** in the sidebar.
10. Stop.

### Clip 08 — `08_experiments_money_proof.mp4` (edit: 03:50–04:23, ~29s)

1. Continue on Experiments & Recovery. Start on the metric strip.
2. Hold on **`Latest lift`**, **`Net incremental GMV`**, and
   **`Sampled payments`**.
3. Scroll to **`Latest recovery batch proof`** and
   **`Why not a payment optimizer alone?`**.
4. Hold long enough that treatment/control counts (58 / 62), incremental
   recovery, cost, net GMV, the positive interval, stopping events, and audit
   references are all readable — this is the film's core financial proof, do
   not rush it.
5. Click **`Download batch report`**.
6. End with the in-app **Recovery Batch Report** modal visible. **Do not**
   let the browser's downloads shelf appear on screen — if it pops up,
   retake and dismiss/hide downloads first (`chrome://settings/downloads` →
   "Ask where to save" off, or just don't let the shelf auto-show).
7. Stop.

### Clip 09 — `09_cohort_funnel_merchant_montage.mp4` (edit: 04:23–04:40, ~8s of this montage)

1. Close the report modal.
2. Navigate to **Cohort Matrix**; hold 4s on the low-success cohorts.
3. Navigate to **Checkout Funnel**; hold 4s on drop-off/recovery metrics.
4. Navigate to **Merchants**; hold 4s on merchant-specific posture.
5. Stop. (Raw ~16–20s total; editor cuts to ~8s across the montage.)

### Clip 10 — `10_model_and_benchmark_montage.mp4`

1. Navigate to **Model Health**; hold on model version, calibration, and the
   promotion pipeline.
2. Click **`View benchmark`**; hold on the frozen-seed label and pass
   thresholds.
3. Stop. (Raw ~14–18s.)

### Clip 11 — `11_audit_montage.mp4`

1. Navigate to **Audit Explorer**; hold on the latest records and the
   chain-integrity state.
2. If a **`Verify chain`** control is visible, click it once and wait for the
   verified toast.
3. **Do not** export or download anything in this clip.
4. Stop. (Raw ~8–12s.)

---

## 2. Retake this clip if you see any of the following

- a disconnected-workspace message or stale "connect local workspace" toast
- a loading skeleton for more than 2 seconds
- visible flicker or an unexpected scroll jump
- a button that should be enabled showing disabled (or vice versa)
- money figures that don't match each other across the clip
- the browser's downloads shelf appearing on screen
- any secret, API key, cookie value, terminal, or DevTools panel visible
- the literal word "demo" anywhere in the product UI

---

## 3. After the live clips are captured

You now have 11 raw `.mp4` files plus whatever pre-roll/tail you gave them.
Everything from here is covered in the master plan and isn't a "manual
recording" step — it's editing:

- **§5** has the exact ElevenLabs narration script, broken into the same
  timestamp blocks as this guide, for generating the voiceover track.
- **§6** has the precise trim points per clip if you want to double-check
  raw vs. edited length.
- **§7** is the Figma-frame insertion plan (7 frames: opening, revenue risk,
  AI boundary, recovery lifecycle, safety controls, complementary-to-routing,
  business proof) with the exact transition/match-cut instructions between
  each Figma frame and the live clip on either side of it.
- **§8** is audio/voice direction (pace, emphasis words, ducking).
- **§11** is the final rubric self-check — watch the assembled film muted
  and confirm each of the four judge questions (problem taste, build
  quality, AI judgment, failure recovery) is answerable from visuals alone
  by the stated timestamp.

## 4. Quick figure reference (for on-screen sanity checks while recording)

| Figure | Value |
| --- | --- |
| Treatment / control | 58 / 62 |
| Treatment recoveries | 30 |
| Gross treatment recovery | ₹25,200 |
| Recovery rate, treatment / control | 51.7% / 17.7% |
| Incremental gross recovery | ₹16,556.13 |
| Intervention cost | ₹20.30 |
| **Net incremental GMV** | **₹16,535.83** |
| 95% interval | ₹8,676.93 – ₹24,394.73 |
| Policy-violating executions | 0 |

If anything on screen doesn't match this table, something in the recording
environment has drifted (most likely: clip 02's injection was clicked more
than once) — stop and re-seed `recording.db` per §0.1 before continuing.
