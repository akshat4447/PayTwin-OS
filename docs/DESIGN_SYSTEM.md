# PayTwin OS — Design System (PayTwin DS v3)

Source of truth: `apps/web/index.html` → `PayTwin DS v3` style block.
Architecture: shadcn/ui-style semantic token layer · Linear-grade dark precision ·
Geist-style typographic restraint (Inter + JetBrains Mono). Single file, no build step.

## 1. Color tokens (semantic · light/dark)

| Token | Dark | Light | Role |
|---|---|---|---|
| `--bg` | #090a0f | #f5f6f9 | Canvas |
| `--bg2` | #0d0f16 | #eef0f5 | Recessed (sidebar, code, traces) |
| `--panel` | #10131b | #ffffff | Card surface |
| `--panel2/--panel3` | #151926/#1c2233 | #f4f6fa/#eaeef5 | Inputs · chips · nested |
| `--line/--line2` | #1f2534/#2c3448 | #e4e8f0/#d2d9e5 | Separator · emphasized |
| `--ink/--mut/--dim` | #f3f5fa/#9aa3b8/#626c82 | #161a26/#5b6579/#8d97ac | primary/secondary/tertiary text |
| `--acc` | #5b6ef5 | #4c61e8 | Actions · selection · focus |
| `--acc2` | #9079f5 | #7a5af8 | Secondary data series |
| `--grn --amb --red --cyan --pink` | #3ecf8e #f5a524 #f04e5e #43c6dd #ee6dd5 | #0ea472 #c47f17 #dd3d52 #0e8fa8 #c339b8 | success/warning/critical/info/aux |

Dark-first: `:root` is dark (`color-scheme:dark`); `[data-theme="light"]` overrides.
Semantic fills are always `color-mix(in srgb, semantic 8–15%, surface)` — color
communicates, never decorates. Ambient depth comes from two fixed radial glows
(`body::before`, accent @7–9%) rather than borders.

## 2. Typography (Inter → system fallback; JetBrains Mono for code)

| Role | Spec |
|---|---|
| Page title (`h1`) | 24/750 · -0.5px |
| Card title (`h2`) | 13/650 · -0.1px |
| Body | 13.5/1.55 · antialiased |
| KPI value (`metric strong`) | 27/750 · -0.8px · tabular-nums |
| Eyebrow (`.trow .eyebrow`) | 10.5/700 · uppercase · 1.5px tracking · accent |
| Nav group (`.nav .grp`) | 10/700 · uppercase · 1.6px tracking · dim |
| Pill/chip | 10.5/650 · 0.4px |
| Mono (`kbd`,`code`,`trace`) | JetBrains Mono → ui-monospace stack |

Restraint rules: weights cap at 750, tracking tightens only on display sizes,
`.num` (tabular-nums) on all financial figures so ₹ values align vertically.

## 3. Spacing & radius
Spacing = 4-base scale (4/8/12/16/20/24/32/40). Radius: control 8 (`--rs`) ·
card 12 (`--r`) · sheet/modal/palette 16 (`--r-lg`) · pill 999 · thumb-corners 6–7.

## 4. Elevation & materials
Three shadows (`--sh-sm/sh/sh-lg`, blue-black tinted `rgba(3,5,12,…)`) — hairline
borders carry most separation; large shadow only on floating layers (drawer,
modal, palette). Sidebar/topbar use translucent material:
`rgba(bg,.72–.75)` + `backdrop-filter: blur(22px) saturate(1.8)`.

## 5. Components (class API unchanged from legacy)
Buttons `.btn` (+`.pr .dn .sm .lg .is-loading`) · fields (input/select/textarea/range)
· pills `.pill.{grn red amb acc mut}` · cards `.card>.hd` · KPI `metric()` markup
(`.mlbl/.mrow/.delta/.bars`) · tables `.tbl` · timeline `.tl(.done/.act)` · causes
`.cause(.a/.r)` · chat `.msg(.you)/.bub/.aiav/.chip` · banner `.banner(.ok)` ·
overlays `.overlay>.modal`, ⌘K palette · toast capsule · chaos console/fab ·
moneyhud · lvl strip · heat matrix `.hc` · code block · empty `.empty` · skeleton `.skel`.

## 6. Motion
`--ease cubic-bezier(.22,.8,.26,.99)`; durations tokenized: fast 140ms, base 220ms,
slow 340ms (fadeup cards, sheetin modals). Press = scale(.98)+brightness; hover =
tint shift (no lift). `prefers-reduced-motion` collapses all durations to ~0.

## 7. Accessibility
`:focus-visible` 2px accent outline @60% + 2px offset on every interactive element;
AA-contrast text pairs in both themes; aria-labels on icon buttons; semantic buttons
throughout; reduced-motion honored; keyboard: ⌘K palette, Esc closes overlays,
full tab order preserved (no positive tabindex introduced).

## 8. Behavior layer (`<script>` block)
Hash routing (#pagename ⇄ S.page), responsive nav (icon rail ≤1080px; off-canvas
drawer ≤768px with scrim + menu button — drawer restores full labels), theme cycle
dark→light→system (matchMedia-driven) incl. `?theme=` URL override, ⌘K palette,
`window.toast()`, `[data-act="how"]` explainer modal. All `data-act`/`data-live`
hooks preserved from v2.

## 9. Captures
`docs/ui-shots/before/overview-1440.png` (v2 baseline) ·
`docs/ui-shots/after/` (23 v3 captures): 14 routes `@-1440.png` (dark),
`overview-light-1440` / `warroom-light-1440`, responsive `overview-{1024,768,390}`,
`overview-390-menu` (drawer open), interaction states `state-{palette,toast,modal}`.

