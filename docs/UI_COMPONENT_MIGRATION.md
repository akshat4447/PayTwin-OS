# UI Component Migration Record

Compatibility boundary: the original `<style>` block remains as the structural
foundation (spacing/layout utilities shared by JS-generated markup); all visual
decisions — color, type, elevation, materials, controls, motion — are governed by
the `apple-ds*` overlay layers that cascade after it. No competing visual language exists.

## Mappings

| Old pattern | New pattern | Where | Status |
|---|---|---|---|
| Navy/violet token set | Semantic neutral+accent tokens (light/dark) | apple-ds :root/[data-theme] | migrated |
| body::before glow gradients | removed (`display:none!important`) | apple-ds base | migrated |
| Gradient sidebar + gradient selection wash | Translucent source-list material + accent-fill selection | apple-ds-2 | migrated |
| Opaque topbar/statusstrip | Sticky toolbar material, hairlines | apple-ds-2 | migrated |
| Gradient primary btn, translateY hover | Solid filled/tinted/tertiary/destructive; press-scale; `.is-loading`; `.lg` | apple-ds-2 | migrated |
| Border-heavy saturated pills/chips | Soft semantic fills, borderless chips | apple-ds-2 | migrated |
| Flat metric card (label/value/delta stacked) | KPI: eyebrow label · 27px tabular value · delta+spark row (`metric()`) | apple-ds-3 + helper rewrite | migrated |
| Uppercase tracked table headers | Sentence-case secondary headers, hairline rows, hover wash | apple-ds-3 | migrated |
| Red-gradient moneyhud | Calm critical card (semantic fill, tabular figure) | apple-ds-4 | migrated |
| Purple you-bubble chat | iMessage-style accent bubble, tailless 16px | apple-ds-3 | migrated |
| Blur-lite overlay/modal | Sheet presentation (blur 20 sat 1.6, 20px radius, scale-fade) | apple-ds-4 | migrated |
| Accent-bordered toast | Floating capsule w/ semantic check | apple-ds-4 | migrated |
| No loading affordance | `.skel` shimmer utility + `.btn.is-loading` spinner | apple-ds-4/-2 | added |
| dark/light toggle only | dark/light/system + `?theme=` override | apple-ds-js | added |
| No deep links | `#pagename` routing + hashchange | apple-ds-js | added |
| Single 1180px breakpoint | 1180 collapse · 1080 icon-rail · 768 off-canvas+scrim+menu-btn | apple-ds-4 | added |

## Intentionally retained (shared foundation)
Layout utilities and structural rules still consumed by generated markup
(grids, pagegrid/trow geometry, tl/chatbox/flex scaffolding, palette results,
heat grid, range labels, chaos items, modal width constraints).
