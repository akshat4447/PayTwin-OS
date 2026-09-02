# PayTwin Figma frame pack

This pack is the source brief for a seven-frame, 16:9 video story that matches the light-theme PayTwin OS product.

## How to use it in Figma

1. Open the supplied Figma design file and create a new page called `PayTwin — Video Story`.
2. Upload or open [`PAYTWIN_FIGMA_GENERATION_PROMPT.txt`](PAYTWIN_FIGMA_GENERATION_PROMPT.txt) in Figma AI / Make, then ask: **“Create the seven named editable desktop frames in this file exactly from the attached specification.”**
3. If Figma asks whether to use a visual direction, select a clean, light, enterprise dashboard direction. Do not select a marketing, 3D, or illustration-based direction.
4. Ensure all frames are `1920 × 1080`; keep the components and frames editable so Jitter can animate the individual layers.
5. Before exporting to Jitter, inspect each frame at 100% and verify that long labels, policy cards, and the metric strip do not clip.

## Structure created by the prompt

| Frame | Story beat | Primary message |
| --- | --- | --- |
| 01 — Opening / PayTwin | Product promise | Detect revenue at risk, recover safely, prove impact. |
| 02 — Revenue risk | Problem | Revenue loss happens across multiple failure paths. |
| 03 — AI judgement / deterministic control | AI boundary | AI explains; policy and code control execution. |
| 04 — Recovery lifecycle | End-to-end credibility | Assigned treatment, signed outcome, measured recovery. |
| 05 — Safety controls | Trust | Bounded policy, stop, cancellation, rollback, and blocked action. |
| 06 — Complementary to routing | Razorpay fit | Routing intelligence plus recovery governance, not a substitute claim. |
| 07 — Business proof | Outcome | Net incremental GMV, confidence, costs, and audit trace. |

## Design-system source

The exact light-theme tokens, fonts, radii, border values, and shadows are taken from the working PayTwin app in [`apps/web/index.html`](../../apps/web/index.html). The build uses Inter for normal UI text and JetBrains Mono for IDs, audit references, compact labels, and time/metric traces.

## Accuracy guardrails

- The money figures are internally consistent with the local canonical recovery batch: 58 treated, 62 control, ₹16,535.83 net incremental GMV, ₹20.30 cost, and a ₹8,676.93–₹24,394.73 95% interval.
- The provider lifecycle must be labeled **“Local Test Mode · Razorpay-shaped lifecycle”** in small provenance copy. It must not imply a connected live Razorpay account.
- Do not show the word “demo” inside any frame.
- The comparison frame must position PayTwin as complementary to payment routing/optimization—not as a claim that it replaces it.

## Jitter handoff

Animate the internal layers, not a flattened full-frame image.

- Opening: stagger masthead, eyebrow, headline, then the three-step flow.
- Risk: animate the three failure cards left-to-right, then the final cohort note.
- Decision boundary: move the connector line through AI Commander → Policy Engine → Recovery Executor; use the red fail-closed band last.
- Lifecycle: advance the four steps and reveal the verified webhook panel after the payment link trace.
- Safety: reveal recommended and review cards, then reveal the blocked card with a short red emphasis pulse.
- Complementary: build the comparison table row-by-row, then connect the four-stage flow.
- Closing: animate the four metrics, then show audit checks and the final `Detect → Decide → Recover → Prove` line.

Use 350–550 ms easing for cards and 600–800 ms for main message changes. Avoid continuous pulsing, bouncing, flickering, or automatic scrolling.
