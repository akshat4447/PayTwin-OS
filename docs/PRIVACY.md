# Privacy

- **No card/PAN/UPI credentials, CVV, tokens, or bank logins are ever stored** — connector
  contracts reject such fields at canonicalization (schema-level).
- Customers are **pseudonymous** (`customer_ref` = salted hash of provider customer id);
  no emails/phones/names in analytics tables.
- Identity separation: contact-bearing actions (payment link) pass recipient refs through
  the connector at execution time; PayTwin stores only the ref + consent predicate result.
- Consent predicates (`consent_on_file`, `dnd_window_ok`) are first-class policy inputs —
  actions without consent evidence are blocked.
- Right-to-erasure: `customer_ref` mapping lives with the merchant connector config;
  PayTwin-side deletion = drop rows by ref (documented procedure).
- LLM safety: no credentials, no raw customer PII in prompts; evidence packs contain
  aggregates + refs only.
- Retention: canonical events 400 days (config), audit records retained (append-only).
