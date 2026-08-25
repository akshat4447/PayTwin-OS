# UI REDESIGN AUDIT — PayTwin OS web console

Date: 2026-08-26 · Target: `apps/web/index.html` (single-file vanilla JS app, 705 lines,
13 client-routed pages, additive LIVE API data layer). No build system, no framework —
the redesign is an in-place design-system replacement with surgical markup upgrades.

## Apple reference used

Local package = official **binary** bundles only (SF fonts/SF Symbols DMGs, Sketch/
Photoshop templates, device bezels) + manifest/license. Fonts & templates are
license-restricted and not redistributable ⇒ per asset-safety rules we derive the
system from HIG principles these packages represent and implement via:
system font stack (-apple-system/SF Pro when installed), CSS-recreated materials,
semantic color model, standard control metrics. Nothing proprietary is committed.

## Current architecture map

- Shell: `render()` builds `.app` = `.sidebar` (brand/wsbtn/nav groups/sidefoot userchip)
  + `.mainwrap` (.topbar search/theme/notifications/envpill · .statusstrip · article.page).
- Routing: `S.page` + `PAGES` map; delegated clicks on `[data-act]` in `wire()`;
  ⌘K palette; Escape closes overlays.
- Pages (13): overview, cohort, warroom, twinlab, policies, commander, experiments,
  modelhealth, audit, integrations, merchants, funnel, bench.
- Shared helpers: `metric()` KPI card, `sparkSVG/bandChart/qini/lineBand/calibCurve/
  funnelSVG/heatMatrix/lvlStrip/streamRows/illShield`, `ic()` 30-glyph inline SVG set.
- LIVE layer (additive, lines 554–705): wraps `render()` for env badge; hydrates
  ORG/MERCH/INC/POLICIES/BLOCKED/MODELS from `/api/*`; intercepts runSim/inject/chat/
  exports when LIVE; 5 s refresh poll. **Untouched by this redesign.**

## Migration table

| CURRENT COMPONENT | CURRENT STYLE | APPLE-EQUIVALENT PATTERN | ACTION | STATUS |
|---|---|---|---|---|
| Color tokens (--bg…--pink) | Cool navy/violet palette, saturated gradients | Semantic system grays + Apple accent/semantic colors, light+dark | Replace token values, add elevation/material tokens | done |
| body::before radial gradients | Decorative AI-glow | None — flat calm surfaces | Remove | done |
| .sidebar | Gradient bg, heavy borders, colored selection gradient | Translucent source-list material (blur+saturate), hairline separator, macOS accent-fill selection | Restyle + material tokens | done |
| .nav .item.on | Gradient wash + inset bar | Solid accent-fill rounded selection, white label (macOS) | Restyle | done |
| .topbar/.statusstrip | Opaque stacked bars | Sticky translucent toolbar material, hairline dividers | Restyle | done |
| .btn (+.pr/.dn/.sm) | Gradient primary, translateY hover bounce | Solid filled/tinted/tertiary/destructive; press=opacity, hover=tint shift; loading spinner; icon btn | Restyle + add .is-loading,.icon-only,.lg | done |
| inputs/select/textarea/range | Generic focus ring | 44px-class fields? no—compact 8/12 padding, accent ring 3px 35%, tinted track thumb | Restyle | done |
| .card / .metric | Flat panel, shadow-heavy, fadeup | Grouped inset surface, hairline border, soft ambient shadow, hover raise on interactive | Restyle + .card.hoverable | done |
| metric() KPI markup | label/value/delta cramped | Eyebrow label · tabular 28px value · delta pill · right spark | Rewrite helper output | done |
| .tbl | Uppercase tracked headers everywhere | Caption-style secondary headers, row hover, hairline rows, numeric alignment | Restyle | done |
| .pill tones | Saturated tinted chips | Softer semantic fills w/ dot option | Restyle values | done |
| .moneyhud | Multi-gradient red/purple banner | Calm critical card: semantic fill, big tabular figure, supporting stats | Restyle | done |
| chat bubbles (.msg/.bub) | Purple gradient you-bubble | iMessage-style: gray received / accent-filled sent, 16px radius | Restyle | done |
| .overlay/.modal/.palette | Dark blur, 18px radius | Sheet presentation: thicker material, 20px radius, scale-fade in | Restyle + keyframes | done |
| .toast | Accent-bordered box | Compact floating capsule, subtle shadow | Restyle | done |
| Empty states (.empty + illShield) | Plain copy | Contextual copy + illustration kept, better type | Restyle only | done |
| Loading | typing dots (commander only) | + shimmer skeleton utility .skel (used by twin result slot pre-run) | Added | done |
| Icons ic() | 1.8 stroke mixed set | Normalize 1.6 stroke, round caps (SF-Symbols feel); set unchanged | stroke tweak | done |
| Theme | dark/light toggle only | dark/light/system (matchMedia) with auto icon | Bootstrap script added | done |
| Deep links | none (page state unreachable by URL) | `#pagename` hash routing + hashchange | Bootstrap script added | done |
| Responsive | single 1180px collapse | ≤1024 icon rail sidebar; ≤768 off-canvas + menu button + backdrop | Media queries + menu handler | done |
| Motion | fadeup/pulse/blink | cubic-bezier(.25,.1,.25,1), durations 0.18–0.3s, reduced-motion respected (kept) | Refined | done |

## Functional preservation contract

All `data-act` / `data-p` / `data-k` / `data-q` / `data-live` hooks, element ids
(#app,#chatbox,#cmdIn,#trace,#palIn,#palRes,#livechip), class hooks JS queries
(.envpill,.iconbtn .ping,.toastwrap,[data-live=*]), and the entire LIVE layer remain
byte-identical unless explicitly noted above.

## Before/after captures

docs/ui-shots/before/overview-1440.png (pre-redesign). After-captures land in
docs/ui-shots/after/*.png at 1440/1024/390 across key routes once migration lands.
