# Agent Architecture (AI Incident Commander)

## Principle
The LLM is an **evidence-grounded operator assistant**. It can investigate, explain,
recommend, rank, draft. It can NEVER move money.

## Request path
```
user message → intent classifier (deterministic, regex+keyword, LLM-optional)
  → READ-ONLY tools (tenant-scoped):
      get_incident · list_incidents · query_metrics · get_twin_run
      get_experiment · get_policy · explain_decision · get_audit
  → evidence pack (ordered, ided: E1..En)
  → composer → answer_md + citation chips [INC-…, evt_…, metric.…, DEC-…]
```
Write-intents (retry/refund/reroute/link/notify) are classified as `action_request`:
the agent produces a **typed ActionRequest** → policy engine evaluates → reply contains
ALLOWED (with execution id via normal executor path) or BLOCKED (failed rules, plain-language
reason, "no customer/payment action was executed") or APPROVAL_REQUIRED. The chat channel
itself never executes.

## Providers
`LlmProvider` protocol: `none` (default) → deterministic composer: template + evidence
grounding (every claim must reference an evidence id; ungrounded sentences are dropped).
`openai`/`anthropic` enabled via env when keys exist; same tools, same evidence pack,
temperature 0, system prompt forbids fabrication, answers must cite E-ids.

## Safety
- Prompt-injection resistance: tool outputs are data, never instructions (structured
  evidence objects; no raw provider payloads into the prompt; payment credentials never
  enter any prompt).
- Every chat turn stores: tools used (name/args/latency), evidence ids, mode
  (hosted|fallback), citations — auditable.
- Refusal eval set: 6 adversarial prompts must refuse or route to policy (tested).
- Golden eval: 12 Q/A pairs checked for grounding (every citation resolves) (tested).
