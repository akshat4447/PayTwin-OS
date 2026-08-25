# PayTwin OS — Design System (Apple-inspired)

Source of truth: `apps/web/index.html` → `<style id="apple-ds">` blocks 1–4.
Reference: local Apple Design Resources packages (HIG principles); system fonts only.

## 1. Color tokens (semantic · light/dark)

| Token | Dark | Light | Role |
|---|---|---|---|
| `--bg` | #101013 | #f5f5f7 | Canvas |
| `--bg2` | #161619 | #ececef | Recessed (code, traces) |
| `--panel` | #1c1c21 | #ffffff | Card surface |
| `--panel2/--panel3` | #232329/#2b2b33 | #f5f5f7/#eef0f3 | Inputs · chips · nested |
| `--line/--line2` | #35353c/#45454e | #e3e3e8/#d2d2d7 | Separator · emphasized |
| `--ink/--mut/--dim` | #f5f5f7/#98989f/#6b6b73 | #1d1d1f/#6e6e73/#aeaeb2 | primary/secondary/tertiary text |
| `--acc` | #0a84ff | #0071e3 | Actions · selection · focus |
| `--acc2` | #5e5ce6 | #5856d6 | Secondary data series |
| `--grn --red --amb --cyan --pink` | #30d158 #ff453a #ff9f0a #64d2ff #ff375f | #248a3d #d70015 #b25000 #0e7a8d #d61f69 | success/critical/warning/info/aux |

Semantic fills are always `color-mix(in srgb, semantic 8–15%, surface)` with no
border-heavy chips — color communicates, never decorates.

## 2. Typography (system SF stack: -apple-system → SF Pro Text)

| Role | Spec |
|---|---|
| Page title (`h1`) | 26/700 · -0.55px |
| Card title (`h2`) | 13/600 |
| Body/sub | 13.5 · secondary #mut |
| KPI value (`metric strong`) | 27/700 · -0.7px · tabular-nums |
| Eyebrow | 10.5/600 · uppercase · 1.1px tracking · dim |
| Table header | 11/600 sentence case |
| Mono (`chip`,`code`,`trace`) | ui-monospace SF Mono stack |

Financial figures always `.num` (tabular) — ₹ values align vertically in tables/KPIs.

## 3. Spacing & radius
Spacing = 4-base scale (4/8/12/16/20/24/32/40). Radius: control 8 (`--rs`) ·
card 14 (`--r`) · sheet/modal/palette 20 (`--r-lg`) · pill 999 · thumb-corners 6–7.

## 4. Elevation & materials
Three shadows (`--sh-sm/sh/sh-lg`) — hairline borders carry most separation;
ambient shadow only on floating layers. Sidebar/topbar use translucent material:
`rgba(bg,.72-.75)` + `backdrop-filter: blur(22px) saturate(1.8)`.

## 5. Components (class API unchanged from legacy)
Buttons `.btn` (+`.pr .dn .sm .lg .is-loading`) · fields (input/select/textarea/range)
· pills `.pill.{grn red amb acc mut}` · cards `.card>.hd` · KPI `metric()` markup
(`.mlbl/.mrow/.delta/.bars`) · tables `.tbl` · timeline `.tl(.done/.act)` · causes
`.cause(.a/.r)` · chat `.msg(.you)/.bub/.aiav/.chip` · banner `.banner(.ok)` ·
overlays `.overlay>.modal`, palette · toast capsule · chaos console/fab · moneyhud ·
lvl strip · heat matrix `.hc` · code block · empty `.empty` · skeleton `.skel`.

## 6. Motion
`--ease cubic-bezier(.25,.1,.25,1)`; fadeup 340ms (cards), sheetin 340ms (modals),
fast interactions 160ms; press = scale(.98)+brightness; hover = tint shift (no lift).
`prefers-reduced-motion` collapses all durations to ~0.

## 7. Accessibility
Focus-visible ring 3px @38% accent on every interactive element; AA-contrast text
pairs in both themes; aria-labels on icon buttons; semantic buttons throughout;
reduced-motion honored; keyboard: ⌘K palette, Esc closes overlays/sheets,
full tab order preserved (no positive tabindex introduced).

## 8. Behavior layer (`<script id="apple-ds-js">`)
Hash routing (#pagename ⇄ S.page), responsive nav (menu-btn + scrim ≤768px),
theme cycle dark→light→system (matchMedia-driven) incl. `?theme=` URL override,
topbar theme-icon resolution post-render.
