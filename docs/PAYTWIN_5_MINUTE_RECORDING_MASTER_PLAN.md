# PayTwin OS — five-minute Buildathon recording master plan

## 1. The outcome this film must prove

This is not a feature tour. It is one continuous business story:

> A merchant is losing revenue in one payment cohort. PayTwin forecasts the exposure, introduces the event, diagnoses the cause, selects a bounded intervention, refuses unsafe work, exercises a Razorpay-shaped payment lifecycle, proves failure controls, and measures net incremental GMV against a control.

The judge should be able to answer all four evaluation questions before the final frame:

| Buildathon question | Answer the film must establish | On-screen proof |
| --- | --- | --- |
| Problem taste | Payment failures become lost revenue through several paths, and the recovery window closes quickly. | Figma revenue-risk frame, Command Center, cohort-scoped incident. |
| Build quality | The product runs end to end, uses structured states and evidence, and exposes testable controls. | Scenario Lab, War Room, local Razorpay lifecycle, Reliability Lab, audit and benchmark montage. |
| AI judgment | AI diagnoses, ranks, explains, cites and abstains. Deterministic code authorizes and executes. | AI boundary frame, Commander tool trace and refusal, typed policy rules. |
| Failure recovery | The film shows a real broken state, a blocked release, a corrected handler, a forged callback rejection, and runtime rollback/stop behavior. | War Room rollback state and Reliability Lab broken → blocked → corrected → ready flow. |

The final business claim is deliberately narrow and defensible:

- 58 treatment payments and 62 control payments.
- 30 treatment recoveries worth ₹25,200 gross treatment recovery.
- 51.7% treatment recovery versus 17.7% control recovery.
- ₹16,556.13 incremental gross recovery.
- ₹20.30 intervention cost.
- ₹16,535.83 net incremental GMV.
- 95% net interval: ₹8,676.93 to ₹24,394.73.
- Zero policy-violating executions.

Do not call this a live Razorpay account or a production deployment. The accurate, stronger statement is: **production-grade architecture and safety controls exercised through credential-free Razorpay local Test Mode**.

## 2. Required correction before animation

Check Figma frame `07 — Business proof` before export. The precise values must match the reproducible local recovery batch below.

The arithmetic must read:

```text
₹16,556.13 incremental gross recovery
−    ₹20.30 intervention cost
= ₹16,535.83 net incremental GMV
```

Keep the 95% interval `₹8,676.93–₹24,394.73`. Never mix the older month-to-date placeholder values with this canonical recovery batch.

## 3. Editorial rules

- Master format: 1920 × 1080, 30 fps, 16:9, exactly 5:00 or shorter.
- Voice: confident Indian English, conversational rather than announcer-like, 132–138 words per minute.
- Record the product in the light theme at 100% browser zoom.
- Crop browser chrome in the final edit. Keep the app sidebar because it helps judges understand product breadth.
- Use one browser tab and one connected workspace for continuity.
- Use Figma for the problem, system boundary, process and outcome. Use the real product for every proof claim.
- No decorative typing animation over live metrics. Let the actual product state be readable.
- Hold every terminal state for at least 1.5 seconds.
- Use straight cuts, restrained 180–250 ms dissolves, and match cuts. Avoid zoom-whip, bounce, glow loops, flicker and auto-scroll.
- Do not show keys, cookies, local storage, terminals, source code, DevTools, test runners, or notifications in the five-minute film.
- Do not say that PayTwin replaces Razorpay Optimizer. The product is complementary to routing.

## 4. Five-minute master timeline

| Time | Visual source | What happens | Rubric proof |
| --- | --- | --- | --- |
| 00:00–00:12 | Figma 01 | Product promise and net-GMV outcome animate in. | Problem + impact |
| 00:12–00:27 | Figma 02 | Payment degradation, checkout abandonment and mandate failure connect into one revenue-loss chain. | Problem taste |
| 00:27–00:47 | Live B01 | Command Center → click `Start operational flow` → Scenario Lab opens. | It runs; coherent starting point |
| 00:47–01:14 | Live B02 | Review forecast → `Introduce scenario events` → `Compare response options` → open incident evidence. | Prediction, separation of forecast/observation, bounded decision |
| 01:14–01:38 | Live B03 | War Room shows INC-2481, causal evidence, candidate ranking, blocked action and rollback/stopping controls. | AI evidence + failure recovery |
| 01:38–01:50 | Figma 03 | AI Commander → Policy Engine → Recovery Executor boundary. | AI judgment |
| 01:50–02:14 | Live B04 | `Why this action?` then `Retry everything now`; show citations/tool trace and refusal. | Grounding + deliberate non-use of AI |
| 02:14–02:21 | Figma 05 | Six hard controls appear: consent, quiet hours, caps, provider health, cancellation, rollback. | Trust boundary |
| 02:21–02:39 | Live B05 | Policies: inspect YAML, show blocked request, run historical replay. | Deterministic governance + fail closed |
| 02:39–02:45 | Figma 04 | Assign → issue → verify → fulfil once → measure. | Process clarity |
| 02:45–03:10 | Live B06 | Create order → capture local payment → verify Checkout → record fulfilment. | Razorpay-shaped build quality |
| 03:10–03:50 | Live B07 | Run control check → pause on BLOCKED → verify corrected handler → forged signature rejected. | Failure recovery + test-the-tester |
| 03:50–04:23 | Live B08 | Experiments & Recovery shows treatment/control money proof and opens downloadable report. | Measured business impact |
| 04:23–04:40 | Live B09–B11 montage | Cohort, funnel, merchant, model health, benchmark and audit surfaces. | Product breadth + trust |
| 04:40–04:52 | Figma 06 | Optimizer and PayTwin are shown as complementary controls. | Razorpay fit |
| 04:52–05:00 | Figma 07 | Net-GMV proof, audit check and closing loop. | Complete judge answer |

## 5. Exact narration, aligned to the timeline

The following is the final ElevenLabs script. Keep the paragraph boundaries because each paragraph is one edit block.

### 00:00–00:12 — opening promise

Revenue loss rarely arrives as one clean failure. It leaks through degraded payments, abandoned checkouts, failed mandates, and delayed collections, while the recovery window keeps shrinking.

**Visual cue:** On “recovery window”, finish the Figma animation on `₹16.5K net incremental GMV`.

### 00:12–00:27 — why the problem matters

Most systems stop at alerting. The business problem is closing the loop: identify the exact failing cohort, choose the least harmful intervention, recover the money, and prove the result against a control without over-contacting customers.

**Visual cue:** Reveal payment degradation first, checkout abandonment second, and mandate failure third. Connect them only after “closing the loop”.

### 00:27–00:47 — Command Center

This is PayTwin OS, an AI revenue-recovery control plane. The Command Center rolls up four merchants, current success rate, active incidents, and GMV at risk. I’ll start a flash-sale plus issuer-failure scenario and follow the same operating flow an on-call team would use.

**Click cue:** Click `Start operational flow` on “start”. The Scenario Lab heading should be stable by the final word.

### 00:47–01:14 — forecast, inject and compare

Before changing any payment event, Scenario Lab produces a pre-incident forecast: the affected cohort, an eighty-percent risk range, and bounded recovery options from a fixed-seed, four-hundred-trial digital twin. The forecast stays separate from observed data. Now I introduce the scenario events, then compare responses. PayTwin can recommend a narrow action while rejecting a larger option that violates the merchant’s blast-radius policy.

**Click cues:**

1. Hold on the forecast during “pre-incident forecast”.
2. Click `Introduce scenario events` on “introduce”.
3. Wait for the success toast and data to settle.
4. Click `Compare response options` on “compare”.
5. Show the recommended, review and blocked cards.
6. Click `Open incident evidence` at the end.

### 01:14–01:38 — Incident War Room

The War Room is scoped to incident INC-2481, not a portfolio-wide guess. It shows the timeline, ranked causal evidence, revenue at risk, expected value for each candidate, and stopping budgets. One action is policy-allowed; a full reroute is blocked, and the runtime path rolls back if provider health or success rate crosses its guard.

**Visual cue:** Move the cursor from incident ID → causal evidence → allowed candidate → blocked candidate → stopping rules. Do not click `Mark resolved` or `Halt autopilot`.

### 01:38–01:50 — AI judgment boundary

Here is the judgment boundary: AI ranks and explains cited evidence. Deterministic policy authorizes; idempotent code executes. Missing evidence means abstain, and missing policy means fail closed.

**Visual cue:** Animate the connector across AI Commander, Policy Engine and Recovery Executor. Reveal the fail-closed band last.

### 01:50–02:14 — Commander explanation and refusal

In AI Commander, I ask why this action was chosen. The answer stays grounded in the selected incident and exposes a read-only tool trace. Then I ask to retry everything. The system refuses because retry caps and quiet-hour rules would be violated. The LLM never moves money and never becomes the policy engine.

**Click cues:** Click `Why this action?`, wait for the complete response, then click `Retry everything now`. Stop only when the refusal and policy citations are visible.

### 02:14–02:21 — safety controls

The hard boundaries are consent, quiet hours, retry and value caps, provider health, cancellation, and rollback.

**Visual cue:** Use Figma frame 05 as a six-second bridge. Do not animate the full comparison panel yet; highlight the six controls.

### 02:21–02:39 — typed policies

Those boundaries are typed, versioned policies. We can inspect the actual rules, replay a draft against history, and see every blocked request. Even an intervention with higher theoretical recovery is stopped before execution when it exceeds the merchant’s approved scope.

**Click cues:** Open one `View YAML` modal, hold, close it, then scroll to `Rehearse before you save` and click `Run historical replay`. Keep a deliberately blocked request visible for at least two seconds.

### 02:39–02:45 — attributable lifecycle

Only assigned treatment customers enter this attributable lifecycle: issue, verify, fulfil once, and measure.

**Visual cue:** Animate Figma frame 04 through the four steps. Keep the provenance chip visible.

### 02:45–03:10 — Razorpay-shaped local lifecycle

Here is the code path in credential-free Razorpay local Test Mode. I create an order, materialize a raw-body HMAC-signed payment webhook, verify Checkout server-side, and record exactly one fulfilment. The same durable inbox, state machine, idempotency, and audit path handles the result. This does not claim a live account; it proves the provider-shaped lifecycle safely and reproducibly.

**Click cues:** Click `Create order`, `Capture local payment`, `Verify Checkout`, and `Record fulfilment`, waiting for each next button to enable. Finish on `Fulfilment recorded exactly once.`

### 03:10–03:50 — what broke and how it recovered

Trust also requires showing what breaks. In Reliability Lab I run a known-broken handler that permits duplicate fulfilment. The invariant catches it and the release gate blocks. I then verify the corrected one-fulfilment handler, and the gate returns ready. Next I inject a forged signature; it is rejected with zero payment or fulfilment side effects. The suites also cover duplicate delivery, timeout redelivery, out-of-order events, late authorization, refund limits, tenant isolation, rate limits, server errors, and partial success. Known-broken mutations must fail, so this tests the tester, not only the happy path.

**Click cues:**

1. Click `Run control check`.
2. Hold the `FIXTURE BLOCKED` and `BLOCKED` state for two seconds.
3. Click `Verify corrected handler`.
4. Hold `ONE FULFILMENT VERIFIED` for two seconds.
5. Scroll to `Webhook Lab · fault injection`.
6. Click `Forged signature`.
7. End with `Forged signature rejected` and `zero side-effects` visible.

### 03:50–04:23 — money proof

The final business proof is Experiments and Recovery, not a vanity metric. This batch assigned fifty-eight payments to treatment and sixty-two to control, with thirty treatment recoveries worth twenty-five thousand two hundred rupees. After the matched-control expectation and twenty rupees thirty paise of intervention cost, net incremental GMV is sixteen thousand five hundred thirty-five rupees and eighty-three paise. Its ninety-five-percent interval stays positive. The report includes sample size, costs, stopping events, and audit references.

**Visual cue:** Pause first on treatment/control, then net incremental GMV, then the positive interval. Click `Download batch report` and hold the in-app Recovery Batch Report modal.

Use the exact numeric Figma end card for the precise interval: `₹8,676.93–₹24,394.73`.

### 04:23–04:40 — breadth and build quality montage

The same evidence continues across the product: Cohort Matrix scopes degradation; Checkout Funnel extends recovery to abandonment; merchant views specialize each business; Model Health and the frozen-seed Benchmark expose evaluation and calibration; Audit Explorer verifies the decision chain.

**Visual cue:** Five fast but readable shots, roughly four seconds each. Use hard cuts on the nouns “Cohort”, “Checkout”, “merchant”, “Model”, and “Audit”.

### 04:40–04:52 — why not Optimizer alone

PayTwin complements Razorpay Optimizer. Optimizer chooses a route; PayTwin governs what happens after failure: whether to intervene, within which guardrails, and how to prove the incremental impact.

**Visual cue:** Animate Figma frame 06 row by row, then finish on the combined four-stage flow.

### 04:52–05:00 — close

The loop judges can trust: detect the right problem, apply bounded judgment, recover safely, and prove the money.

**Visual cue:** Finish on `Detect → Decide → Recover → Prove`, with `₹16,535.83 net incremental GMV` and `0 unsafe executions` still visible.

## 6. Live browser clip specification

Record all browser footage as one continuous session, but save or cut it at the markers below. Keep 1.5 seconds of overlap at both ends so Jitter can create match cuts.

### B01 — `01_command_center_to_scenario_lab.mp4`

- Start URL: `http://127.0.0.1:8011/#overview`
- Required start state: `LOCAL WORKSPACE · CONNECTED`, no modal, light theme, page at top.
- Hold: organization name, GMV at risk, success rate, active incident count.
- Action: hover `Start operational flow` for 0.5 seconds and click once.
- End state: Scenario Lab is fully rendered and `Pre-incident scenario forecast` is visible.
- Raw target length: 28–35 seconds; edited use: 22 seconds.

### B02 — `02_forecast_inject_compare.mp4`

- Start state: same Scenario Lab frame as B01’s last frame.
- Hold the scenario name, risk range and bounded-response line.
- Click `Introduce scenario events`; wait for `Scenario events introduced`.
- Click `Compare response options`; wait until the decision comparison renders.
- Scroll once, slowly, to show recommended, review and blocked policy cards.
- Return to the guided-flow actions and click `Open incident evidence`.
- End state: Incident War Room is stable.
- Raw target length: 40–50 seconds; edited use: 30 seconds.

### B03 — `03_war_room_evidence_and_rollback.mp4`

- Start state: selected incident is `INC-2481`.
- Hold the incident title and presentation state.
- Slowly point to causal evidence, the EV-ranked decision panel, blocked full reroute and stopping rules.
- If a rollback banner is present, hold it for two seconds. Do not create a new action for the recording.
- Click `Ask Commander` only after the decision panel has been readable.
- End state: AI Commander is stable.
- Raw target length: 30–35 seconds; edited use: 25 seconds.

### B04 — `04_commander_explain_and_refuse.mp4`

- Click `Why this action?` once.
- Wait for the entire answer and tool trace. Do not cut during streaming text.
- Click `Retry everything now` once.
- Wait until the refusal mentions `max_attempts`, `dnd_window_ok` or policy-blocked evidence.
- Keep the banner `AI ranks and explains; deterministic controls decide and execute` in the establishing shot.
- End by clicking `Policies` in the sidebar and allow the page to settle.
- Raw target length: 30–40 seconds; edited use: 20 seconds.

### B05 — `05_typed_policies_and_block.mp4`

- Hold the operating-inside-active-policies banner and blocked count.
- Click the first `View YAML`, hold actual typed rules for 1.5 seconds, then close.
- Point to the deliberately blocked intervention.
- Scroll to `Rehearse before you save`.
- Click `Run historical replay`; wait for `Historical replay complete`.
- End by clicking `Integrations` and allowing it to settle.
- Raw target length: 30–40 seconds; edited use: 17 seconds.

### B06 — `06_local_razorpay_lifecycle.mp4`

- Required state: `Workspace connected`; all four lifecycle cards render.
- Click `Create order`; wait until the order ID appears and capture enables.
- Click `Capture local payment`; wait for `verified + materialized` and Checkout verification to enable.
- Click `Verify Checkout`; wait for the verified state.
- Click `Record fulfilment`; wait for `Fulfilment recorded exactly once.`
- Do not click refund in the main five-minute cut. Record it as an optional extra clip if desired.
- End by clicking `Reliability Lab` and allowing it to settle.
- Raw target length: 35–45 seconds; edited use: 26 seconds.

### B07 — `07_reliability_break_fix_forge.mp4`

- Click the guided proof’s `Run control check`, not a generic suite row.
- Wait for `Duplicate fulfilment control caught`, `BLOCKED`, and `FIXTURE BLOCKED`.
- Hold two seconds.
- Click `Verify corrected handler`.
- Wait for `Correction verified` and `ONE FULFILMENT VERIFIED`.
- Scroll to `Webhook Lab · fault injection`.
- Click `Forged signature`.
- End only when `Forged signature rejected` and zero side effects are visible.
- Click `Experiments & Recovery` after a two-second tail.
- Raw target length: 45–55 seconds; edited use: 36 seconds.

### B08 — `08_experiments_money_proof.mp4`

- Start on the metric strip.
- Show `Latest lift`, `Net incremental GMV`, and sampled payments.
- Scroll to `Latest recovery batch proof` and `Why not a payment optimizer alone?`.
- Make treatment/control, incremental recovery, cost, net GMV, interval, stops and audit references readable.
- Click `Download batch report`.
- End with the in-app `Recovery Batch Report` modal visible; do not show the downloads shelf.
- Raw target length: 35–45 seconds; edited use: 29 seconds.

### B09 — `09_cohort_funnel_merchant_montage.mp4`

- Close the report modal.
- Navigate to `Cohort Matrix`; hold four seconds on low-success cohorts.
- Navigate to `Checkout Funnel`; hold four seconds on drop-off and recovery.
- Navigate to `Merchants`; hold four seconds on merchant-specific posture.
- Raw target length: 16–20 seconds; edited use: 8 seconds.

### B10 — `10_model_and_benchmark_montage.mp4`

- Navigate to `Model Health`; hold model version, calibration and promotion pipeline.
- Click `View benchmark`; hold the threshold gates and frozen-seed label.
- Raw target length: 14–18 seconds; edited use: 7 seconds.

### B11 — `11_audit_montage.mp4`

- Navigate to `Audit Explorer`.
- Hold latest records and the chain-integrity state.
- If a `Verify chain` control is visible, click it once and wait for the verified toast.
- Do not export files in this montage.
- Raw target length: 8–12 seconds; edited use: 5 seconds.

## 7. Figma-to-Jitter insertion plan

Use the seven prepared Figma frames as editable layers, not flattened screenshots.

| Figma frame | Master location | Jitter treatment |
| --- | --- | --- |
| 01 — Opening / PayTwin | 00:00–00:12 | Stagger label, headline, three-step loop, then metric card. |
| 02 — Revenue risk | 00:12–00:27 | Reveal three loss paths left-to-right; connect them into one loop. |
| 03 — AI judgement / deterministic control | 01:38–01:50 | Animate one connector; reveal fail-closed band last. |
| 04 — Recovery lifecycle | 02:39–02:45 | Six-second fast sequence: assign → issue → verify → measure. |
| 05 — Safety controls | 02:14–02:21 | Highlight six hard controls; keep comparison panel in the background. |
| 06 — Complementary to routing | 04:40–04:52 | Table rows appear quickly; end on combined flow. |
| 07 — Business proof | 04:52–05:00 | Metrics count in once; zero unsafe executions lands last. |

Transition rules:

- Figma 02 → B01: match the “failing cohort” card to the Command Center incident card.
- B03 → Figma 03 → B04: use an L-cut; narration continues while War Room fades into the AI boundary and then into Commander.
- B04 → Figma 05 → B05: match the red refusal state to the red blocked-policy card.
- B05 → Figma 04 → B06: match the policy-approved action to the first `Create order` lifecycle card.
- B08 → montage: close the report modal on a cut, then use five four-second product shots.
- Figma 06 → Figma 07: keep the same masthead location so the final transition feels like one system.

## 8. Audio and voice direction

Use a natural, senior product-builder delivery—not a trailer voice.

- Accent: clear Indian English.
- Pace: 132–138 words per minute.
- Tone: calm conviction; slightly faster on mechanics, slower on financial proof.
- Pause for 250–350 ms after: `INC-2481`, `fails closed`, `exactly one fulfilment`, and `net incremental GMV`.
- Emphasize: `against a control`, `deterministic policy`, `blocked`, `zero side effects`, and `₹16,535.83`.
- Do not add exaggerated sound effects. Use one quiet click bed and a restrained low-volume music bed if desired.
- Duck music by at least 8 dB beneath narration and remove it entirely during the exact money calculation.

## 9. Recording readiness checklist

### Product state

- [ ] `http://127.0.0.1:8011/#overview` loads.
- [ ] Top bar says `LOCAL WORKSPACE · CONNECTED`.
- [ ] No key is present in the URL after the workspace session is established.
- [ ] Command Center shows canonical incident data and the featured operational flow.
- [ ] Experiments & Recovery shows 58 treatment, 62 control and positive net incremental GMV.
- [ ] Integrations shows the four local lifecycle controls.
- [ ] Reliability Lab shows the guided control proof.
- [ ] Light theme is active and text contrast is readable.
- [ ] Browser zoom is 100%, app scroll is at top, no modal is open.

### Capture environment

- [ ] 1920 × 1080 capture region at 30 fps.
- [ ] Prefer a browser-window or fixed-region capture. Use full-display capture only when the browser is the sole visible window.
- [ ] Browser chrome cropped or excluded.
- [ ] Desktop notifications, password manager bubbles and update prompts are disabled.
- [ ] Only the PayTwin tab is visible.
- [ ] A five-second throwaway capture proves whether browser-controlled pointer movement is visible in the recorded video.
- [ ] If the pointer is not captured, record clean footage and add one consistent cursor layer in Jitter; do not mix visible and invisible cursor shots.
- [ ] Cursor is normal size; any halo is added later in Jitter.
- [ ] One dry navigation pass completed without mutating the scenario or payment lifecycle.
- [ ] At least 15 GB free disk space.

### Retake conditions

Retake a clip if any of the following appears:

- a disconnected workspace message;
- skeletons or loading states for longer than two seconds;
- a stale “connect local workspace” toast;
- visible flicker or a scroll jump;
- a disabled button that should be enabled;
- inconsistent money figures;
- a browser download shelf;
- a secret, workspace key, terminal or DevTools;
- the word “demo” inside the product UI.

## 10. Copy-paste prompt for the browser recording LLM

Use the prompt below unchanged. It is intentionally limited to browser operation and raw clip capture; narration and Figma animation happen later.

```text
You are the browser recording operator for a five-minute product film. Your job is to capture only clean, silent, live PayTwin OS browser footage. Do not narrate, edit, invent data, modify source code, inspect secrets, or open developer tools.

TARGET
- App: http://127.0.0.1:8011/#overview
- Use the existing authenticated browser session in one tab.
- Required visual state: light theme, 100% zoom, 1920×1080 viewport if supported.
- Never inspect or reveal cookies, local storage, session storage, API keys, request headers, environment variables, terminals, source code or downloads.
- Interact only through visible UI controls. Do not set application state with JavaScript.

PRE-FLIGHT
1. Open the target URL and wait until the app is fully rendered.
2. Confirm the visible top bar says LOCAL WORKSPACE · CONNECTED.
3. Confirm Command Center, Integrations, Reliability Lab and Experiments & Recovery render real content rather than connection placeholders.
4. Confirm Experiments & Recovery contains Net incremental GMV and a treatment/control sample.
5. Return to #overview and perform one hard refresh. Wait for the signed workspace session to restore.
6. If any pre-flight check fails, stop and report the exact visible failure. Do not fake, substitute or continue.

CURSOR AND CAPTURE PROOF
1. Before Clip 01, make a five-second throwaway recording.
2. Use the browser's real pointer/CUA movement, not a DOM-only synthetic click, to move from the page center to Start operational flow and hover without clicking.
3. Stop and inspect the throwaway file. Confirm that the cursor movement and hover are visible and that no other window, notification, terminal or browser credential surface appears.
4. If the cursor is not visible, capture all product clips without relying on cursor choreography and report that one cursor layer must be added in Jitter. Do not mix capture methods across clips.
5. Prefer a browser-window or fixed-region capture. Use full-display capture only if the browser is the only visible window and notifications are disabled.

CAPTURE BEHAVIOR
- Capture silent raw footage only.
- Keep one continuous session so page transitions remain connected.
- Save the clips with the exact filenames below, or record one master take and place markers with these names.
- Give every clip 1.5 seconds of stable pre-roll and 2 seconds of stable tail.
- Move the cursor slowly and purposefully. Hover a primary button for 0.4–0.6 seconds before clicking.
- Click each control once. Wait for its visible result before continuing.
- Use smooth, short scrolls. Never scroll while a page is loading.
- Do not use back/forward navigation. Use product buttons and sidebar navigation.
- If a spinner persists for more than 10 seconds, an error toast appears, the page flickers, or scroll jumps to the top, stop that clip and retake it from its start state.

CLIP 01 — 01_command_center_to_scenario_lab.mp4
Start at #overview. Hold the organization heading, GMV at risk, success rate and active incidents. Click Start operational flow. End only when Scenario Lab and Pre-incident scenario forecast are stable.

CLIP 02 — 02_forecast_inject_compare.mp4
Begin on the same Scenario Lab frame. Hold the scenario, projected risk range and bounded response. Click Introduce scenario events. Wait for the Scenario events introduced success message. Click Compare response options. Wait for results. Smooth-scroll to the recommended, review and blocked policy cards. Return to the guided-flow action area, click Open incident evidence, and end on the stable War Room.

CLIP 03 — 03_war_room_evidence_and_rollback.mp4
Confirm the selected incident is INC-2481. Hold the incident state and at-risk GMV. Point to causal evidence, the policy-allowed candidate, the blocked full reroute and stopping rules. If a rollback state is visible, hold it for two seconds. Do not click Mark resolved, Halt autopilot or request a new execution. Click Ask Commander and end on the stable Commander page.

CLIP 04 — 04_commander_explain_and_refuse.mp4
Click Why this action? Wait for the complete cited answer and read-only tool trace. Click Retry everything now. Wait for the refusal and policy references. Hold the refusal for two seconds. Click Policies in the sidebar and end when the page settles.

CLIP 05 — 05_typed_policies_and_block.mp4
Hold the active-policy banner and blocked-request panel. Click the first View YAML. Hold the actual typed rules for 1.5 seconds, then close the modal. Smooth-scroll to Rehearse before you save and click Run historical replay. Wait for Historical replay complete. Click Integrations and end after all four lifecycle cards render.

CLIP 06 — 06_local_razorpay_lifecycle.mp4
Confirm Workspace connected. Click Create order and wait for the order ID. Click Capture local payment and wait for verified + materialized. Click Verify Checkout and wait for verified. Click Record fulfilment and wait for Fulfilment recorded exactly once. Do not click refund in the main take. Hold the final receipt for two seconds. Click Reliability Lab and end after the guided proof renders.

CLIP 07 — 07_reliability_break_fix_forge.mp4
In Guided Control Proof, click Run control check. Wait for Duplicate fulfilment control caught, BLOCKED and FIXTURE BLOCKED. Hold for two seconds. Click Verify corrected handler. Wait for Correction verified and ONE FULFILMENT VERIFIED. Hold for two seconds. Smooth-scroll to Webhook Lab · fault injection. Click Forged signature. End only when Forged signature rejected and zero side effects are visible. Hold two seconds, then click Experiments & Recovery and let it settle.

CLIP 08 — 08_experiments_money_proof.mp4
Hold Latest lift, Net incremental GMV and Sampled payments. Smooth-scroll to Latest recovery batch proof and Why not a payment optimizer alone? Hold treatment/control, gross recovery, cost, net GMV, positive interval, stopping events and audit references. Click Download batch report. End on the in-app Recovery Batch Report modal. Do not expose the browser downloads shelf.

CLIP 09 — 09_cohort_funnel_merchant_montage.mp4
Close the report modal. Navigate to Cohort Matrix and hold low-success cohorts for four seconds. Navigate to Checkout Funnel and hold drop-off and recovery metrics for four seconds. Navigate to Merchants and hold merchant-specific posture for four seconds.

CLIP 10 — 10_model_and_benchmark_montage.mp4
Navigate to Model Health. Hold model version, calibration and promotion pipeline. Click View benchmark. Hold the frozen-seed label, measured metrics and pass thresholds.

CLIP 11 — 11_audit_montage.mp4
Navigate to Audit Explorer. Hold latest audit records and chain-integrity evidence. If a visible Verify chain control is available, click it once and wait for the verified result. Do not download or export anything.

FINAL QUALITY CHECK
Review every clip for connection errors, loading skeletons, flicker, scroll jumps, clipped text, visible credentials and inconsistent numbers. Report the saved filename, duration, start frame, end frame and any retake needed for each clip. Do not create voiceover or Figma footage.
```

## 11. Final rubric cross-check

Before export, watch the film muted. The story should still be understandable from the visuals alone.

- **Problem taste:** by 00:27 the viewer knows the revenue problem and affected use cases.
- **Build quality:** by 03:10 the viewer has seen forecast, incident, policy, order, webhook, Checkout verification and one fulfilment work in one connected session.
- **AI judgment:** by 02:14 the viewer has seen grounded explanation, tool trace, abstention boundary and refusal.
- **Failure recovery:** by 03:50 the viewer has seen a broken handler blocked, corrected and verified, plus a forged callback rejected.
- **Business impact:** by 04:23 the viewer has seen treatment/control, costs, net incremental GMV, interval and audit references.
- **Razorpay fit:** by 04:52 the viewer understands that PayTwin complements routing and follows provider-shaped lifecycle requirements without pretending to have live credentials.

## 12. Razorpay implementation references used by the story

- Razorpay webhooks are asynchronous server-to-server event notifications; critical user-facing paths can supplement them with an API fetch for verification: https://razorpay.com/docs/webhooks/
- Payment Links support create, fetch, update, cancellation and webhook outcomes: https://razorpay.com/docs/api/payments/payment-links/
- Checkout uses Orders, server-side verification and webhooks for payment state: https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/
- Payment Link outcomes include `payment_link.paid`, and raw webhook bodies must be used for signature verification: https://razorpay.com/docs/webhooks/payment-links/
