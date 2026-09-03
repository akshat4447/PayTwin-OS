# PayTwin OS — manual recording runbook

Companion to [`PAYTWIN_5_MINUTE_RECORDING_MASTER_PLAN.md`](PAYTWIN_5_MINUTE_RECORDING_MASTER_PLAN.md).
That file is the source of truth for narration, Figma treatment and editorial
rules — read it once first. This file is the physical, step-by-step
walkthrough for **you, operating your own mouse and screen recorder**.

The master plan's shot list has 11 live clips, but a Figma frame only ever
sits *between* certain clips — never in the middle of one. That collapses
recording down to **4 continuous takes**: clips 01+02+03 record as one file,
04 and 05 stand alone (Figma frames box them in on both sides), and
06 through 11 record as one more file. Same 11 pieces of footage the final
film needs, four times you actually have to hit record. Once you've recorded
the 4 raw files, hand them off (see §1a) — trimming, cropping and slicing
them into the exact pieces Jitter needs is done with `ffmpeg`, not by hand.

All money figures below were re-verified against a fresh
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

**One button is not safe to repeat: `Introduce scenario events`, partway
through Take 1.** It calls a real chaos-injection endpoint
(`POST /api/chaos/surge_bank_failure`) that adds genuine synthetic events to
the live database. It targets the same cohort as INC-2481 (issuer HDFC ×
method upi_intent), so a second click won't open a *different* incident, but
it will grow the affected-payment count and RaR numbers on screen a little
more each time — meaning if you click it three times while rehearsing, the
numbers you see later in Take 1 (War Room) will be visibly bigger than what's
in this guide.

**Rule: rehearse Take 1 up to and including hovering over `Introduce
scenario events`, but do not click it until the take you intend to keep.**
If you flub anything in Take 1 *after* that click, you have to restart the
whole take — and re-click the injection — which is fine once or twice, but
don't rehearse that way; rehearse only up to the hover.

The local Razorpay lifecycle (inside Take 4 — create order → capture →
verify → fulfil) is safe to repeat too: each run creates a brand-new order,
so retakes just add more historical orders rather than corrupting anything.

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

### 0.4 Recording strategy: 4 takes, not 11 clips and not one long take

Look at the final assembly order (§1a in the master plan, or the Jitter table
in this guide's companion shot-list artifact): a Figma frame sits between
clips 03→04, 04→05, and 05→06. Those are unavoidable hard stops — you have
to end a recording there no matter what. But **nothing** sits between clips
01→02→03, and **nothing** sits between 06→07→08→09→10→11. Those runs can
play through as one unbroken recording and still cut cleanly into the film,
because nothing needs to be spliced into the middle of them.

That gives exactly 4 required starting points:

| Take | Covers original clips | Contains the single-shot click? |
|---|---|---|
| **Take 1** | 01, 02, 03 | Yes — partway through |
| **Take 2** | 04 | No |
| **Take 3** | 05 | No |
| **Take 4** | 06, 07, 08, 09, 10, 11 | No |

Record each take as its own file, named `take1_detect_and_decide.mp4`
through `take4_proof_and_breadth.mp4`. Give every take **1.5 seconds of
stable pre-roll** and a **2-second stable tail**, and — inside a take, at the
point where an original clip boundary falls (noted below) — just keep going;
you don't need to pause, stop, or do anything special there. That boundary
only matters for slicing later, and that's not your job (see §1a).

Take 4 is the longest (~2.5–3 minutes of raw footage) and entirely safe to
retake as a whole if you flub it near the end — nothing in it is destructive.
If that feels too long to nail in one pass, split it at the natural
Reliability-Lab/Experiments boundary into two shorter takes instead; you'll
have 5 files instead of 4, still a big reduction from 11, and neither half
loses any content.

---

## 1. The four takes, in recording order

Timestamps are where the content lands in the final 5:00 edit — they tell you
the eventual length, not how long to record. Record at a natural pace and
don't stop between the bracketed `[from clip N]` markers below; those exist
only so the editor (me) knows where to slice later, not so you know where to
pause.

### Take 1 — `take1_detect_and_decide.mp4` (edit: 00:27–01:38, ~71s combined) — ⚠ contains the single-shot click

*Covers original clips 01, 02, 03.*

1. Navigate to `http://127.0.0.1:8011/#overview`. Confirm
   **`LOCAL WORKSPACE · CONNECTED`**, no modal, scrolled to top.
2. Hold 2s on organization name, GMV-at-risk, success rate, active-incident
   count.
3. Hover **`Start operational flow`** 0.5s, click once. Wait for
   **`Pre-incident scenario forecast`**.
   `[from clip 01 ends here — keep rolling]`
4. Hold 2s on scenario name, 80% risk range, bounded-response line.
5. Click **`Introduce scenario events`** — *the one non-repeatable click in
   this entire guide.* Make sure you mean to keep this take.
6. Wait for the toast **`Scenario events introduced`**. Let it settle.
7. Click **`Compare response options`**. Wait for it to render, scroll down
   slowly **once** to reveal recommended / review / blocked cards.
8. Scroll back up, click **`Open incident evidence`**. Wait for War Room,
   **INC-2481** visible.
   `[from clip 02 ends here — keep rolling]`
9. Confirm **INC-2481** is selected (select it explicitly if not). Hold 1.5s
   on title/state chip.
10. Move slowly, ~1s each: incident ID → causal evidence → allowed candidate
    → blocked full-reroute → stopping rules.
11. If a rollback banner shows, hold it 2s.
12. **Do not click `Mark resolved` or `Halt autopilot`.**
13. Click **`Ask Commander`**, let it settle. **Stop.**

*Narration cues, in order (§5 of the master plan):* "This is PayTwin OS…" →
"Before changing any payment event, Scenario Lab produces a pre-incident
forecast…" → "The War Room is scoped to incident INC-2481, not a
portfolio-wide guess…"

**If you flub this one:** restarting means re-clicking the injection. Fine
once or twice (same cohort, numbers just tick up), not something to do
repeatedly.

### Take 2 — `take2_ai_judgment.mp4` (edit: 01:50–02:14, ~24s)

*= original clip 04, unchanged — a Figma frame sits on both sides of this
one in the final film, so there's nothing to club it with.*

1. Click **`Why this action?`** once. Wait for the **complete** answer and
   tool trace — don't cut mid-stream.
2. Click **`Retry everything now`** once. Wait for the refusal (should cite
   `max_attempts` or `dnd_window_ok`). Hold 2s.
3. Click **`Policies`** in the sidebar, let it settle. **Stop.**

*Narration cue:* "I ask why this action was chosen… Then I ask to retry
everything. The system refuses… The LLM never moves money and never becomes
the policy engine."

### Take 3 — `take3_typed_policies.mp4` (edit: 02:21–02:39, ~18s)

*= original clip 05, unchanged — same reason as Take 2, boxed in by Figma
frames on both sides.*

1. Hold 1.5s on the active-policy banner and blocked count.
2. Click the first **`View YAML`**, hold the typed rules 1.5s, close.
   Confirm you don't see the literal placeholder text
   `(typed rules from API)`.
3. Scroll to **`Rehearse before you save`**, click **`Run historical
   replay`**. Wait for **`Historical replay complete`**.
4. Keep a deliberately blocked request visible ≥2s.
5. Click **`Integrations`** in the sidebar, let it settle. **Stop.**

*Narration cue:* "Those boundaries are typed, versioned policies. We can
inspect the actual rules, replay a draft against history, and see every
blocked request."

### Take 4 — `take4_proof_and_breadth.mp4` (edit: 02:45–04:23 + montage, ~115s combined)

*Covers original clips 06, 07, 08, 09, 10, 11 — the longest take (~2.5–3 min
raw), and entirely safe: nothing in it mutates data destructively, so a
mistake anywhere just means restarting this one take.*

1. On Integrations, confirm all 4 lifecycle cards render. Click **`Create
   order`**, wait for the order ID.
2. Click **`Capture local payment`**. Wait for **`verified + materialized`**.
3. Click **`Verify Checkout`**, wait for verified.
4. Click **`Record fulfilment`**. Wait for **`Fulfilment recorded exactly
   once.`** Hold 2s. Skip refund.
5. Click **`Reliability Lab`**.
   `[from clip 06 ends here — keep rolling]`
6. In **Guided Control Proof**, click **`Run control check`**. Wait for
   **`Duplicate fulfilment control caught`** + **`FIXTURE BLOCKED`**. Hold 2s.
7. Click **`Verify corrected handler`**. Wait for **`Correction verified`** +
   **`ONE FULFILMENT VERIFIED`**. Hold 2s.
8. Scroll to **`Webhook Lab · fault injection`**, click **`Forged
   signature`**. Wait for **`Forged signature rejected`** + zero side-effects.
9. After a 2s tail, click **`Experiments & Recovery`**.
   `[from clip 07 ends here — keep rolling]`
10. Hold on **`Latest lift`**, **`Net incremental GMV`**, **`Sampled
    payments`**.
11. Scroll to **`Latest recovery batch proof`** / **`Why not a payment
    optimizer alone?`** Hold until 58/62, cost, net GMV and interval are all
    readable — don't rush it, this is the film's core financial proof.
12. Click **`Download batch report`**. End on the in-app modal — never the
    browser's downloads shelf.
    `[from clip 08 ends here — keep rolling]`
13. Close the report modal. Navigate **Cohort Matrix**, hold 4s. Navigate
    **Checkout Funnel**, hold 4s. Navigate **Merchants**, hold 4s.
    `[clip 09]`
14. Navigate **Model Health**, hold on version/calibration/pipeline. Click
    **`View benchmark`**, hold frozen-seed label + thresholds. `[clip 10]`
15. Navigate **Audit Explorer**, hold on records + chain-integrity. If
    visible, click **`Verify chain`**, wait for the verified toast. `[clip 11]`
16. **Do not export or download anything here. Stop.**

**Prefer a shorter take?** Split Take 4 at the natural checkpoint after step
9 (Reliability Lab done, about to open Experiments) into `4a` (Razorpay +
Reliability Lab) and `4b` (money proof + montage) — 5 files total instead of
4, still far fewer than 11, nothing lost either way.

---

## 1a. Hand off the raw footage for editing

Once you have the 4 (or 5) raw files, you're done recording — the rest is
editing, and `ffmpeg` (already installed via Homebrew: `brew install
ffmpeg`) does it, not Jitter and not you by hand:

1. **Tell me the file paths** — anywhere in the repo or your home folder is
   fine, e.g. `~/Movies/take1_detect_and_decide.mov`.
2. **You don't need to note cut timestamps.** I'll extract frames
   (`ffmpeg -vf fps=1`) and read them to find the exact moments each
   "wait for" string above appears, then cut precisely on those. If you
   happen to know a rough timestamp for something, mentioning it just saves
   a pass — it's not required.
3. **Tell me your actual capture resolution** if it wasn't exactly
   1920×1080 — I'll scale/pad to match instead of stretching.

What comes back: each take trimmed at head and tail, browser chrome cropped
out if your capture region included any, dead waiting time tightened where a
click took longer to register than expected, exported as clean H.264 `.mp4`
at 30fps — ready to drop straight into Jitter's timeline. Jitter's job then
shrinks to: import those 4 files plus the Figma frames, lay them out per the
timeline table below, add the 7 Figma-frame animations, cut in the
narration, and export.

---

## 2. Retake a take if you see any of the following

- a disconnected-workspace message or stale "connect local workspace" toast
- a loading skeleton for more than 2 seconds
- visible flicker or an unexpected scroll jump
- a button that should be enabled showing disabled (or vice versa)
- money figures that don't match each other across the take
- the browser's downloads shelf appearing on screen
- any secret, API key, cookie value, terminal, or DevTools panel visible
- the literal word "demo" anywhere in the product UI

For Take 1, "retake" means from the very top (Command Center) — there's no
partial-retake option once you've clicked past the injection. For Takes 2–4,
just restart that take; nothing upstream is affected.

---

## 3. After the live takes are captured

You now have 4 raw `.mp4` files (or 5, if you split Take 4). Hand them to me
per §1a — I'll do the trimming, cropping and pacing pass with `ffmpeg` and
return 4 files ready for Jitter. Everything after that is covered in the
master plan:

- **§5** has the exact ElevenLabs narration script, broken into the same
  timestamp blocks as this guide, for generating the voiceover track.
- **§6** has the precise trim points per original clip if you want to
  double-check raw vs. edited length against what I return.
- **§7** is the Figma-frame insertion plan (7 frames: opening, revenue risk,
  AI boundary, recovery lifecycle, safety controls, complementary-to-routing,
  business proof) with the exact transition/match-cut instructions between
  each Figma frame and the live take on either side of it.
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
environment has drifted (most likely: Take 1's injection click was made more
than once) — stop and re-seed `recording.db` per §0.1 before continuing.
