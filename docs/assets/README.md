# Presentation assets

[`forecast-card.svg`](forecast-card.svg) displays every assignment in the
[frozen corrected forecast](../../reports/card_ti2026_rules/recommended_card.json).
It is a forecast card, not the tournament outcome or evidence of predictive skill.
Team names are alphabetical within each category; their order is not a ranking.

Regenerate from the repository checkout, offline:

```bash
.venv/bin/python docs/assets/render_forecast_card.py
```

The renderer checks the input against the
[group replay manifest](../../reports/postmortems/group-replay.manifest.json)
before drawing the card. That manifest is a retrospective attestation, not
original-run provenance. Category counts come from the frozen assignments.
The SVG includes its input path, hash, and manifest reference.

See the [card provenance report](../../reports/card_ti2026_rules/card_provenance.md)
for modeling assumptions and seed sensitivity. The graphic does not rerun the
forecast or change any assignment.
