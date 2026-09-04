# Reproducible Evidence

metrics_card.json is generated, not hand-authored:

```bash
make bench
```

The command evaluates the fixed-seed simulator against its known ground truth
and writes the exact metric card consumed by the submission materials. The
evidence is local synthetic test evidence, not merchant-production telemetry.
