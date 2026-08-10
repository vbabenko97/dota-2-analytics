<!-- ti26-run: 61c63f4aa32c573cdbc7e4abe48e08308801f1ff3cb8e5629a4ae446d5d22b6b manifest.json -->
# D3b calibration gate result -- the multiplicity-corrected Glicko gate

**Verdict: PASS**

Registered 2026-08-03 in `docs/superpowers/specs/2026-08-01-ti2026-forecast-design.md` §II "D3b: the multiplicity-corrected Glicko gate", after the Elo gate (D3) failed on all three conditions and BEFORE Glicko's bootstrap interval was computed.

**This is a ONE-condition test, not three.** Calibrated Glicko's margin and calibration slope were already measured -- computed alongside Elo's diagnostic in the D3 run -- and already pass. They are restated below for the record, not re-tested; the interval is the only quantity that was open when this gate was registered, and it is the actual test.

## Already measured (not under test here)

| condition | value | required | result |
|---|---|---|---|
| margin: mean(LL_constant - LL_glicko_calibrated) | 0.00673 nats/map | >= 0.003 | PASS (already known) |
| calibration slope | 0.9057 | [0.9, 1.1] | PASS (already known) |

**The slope's margin of compliance is fragile: 0.9057 clears the 0.9 lower bound by only 0.0057.** This is stated plainly rather than shown as a bare PASS, so a reader can judge it rather than trust it.

## The actual test: the paired cluster bootstrap interval, at 97.5% not 95%

Bonferroni for the two candidates actually computed (Elo, Glicko): family-wise alpha 0.05 over 2 comparisons gives per-comparison alpha 0.025, hence a 97.5% two-sided interval -- STRICTER than the Elo gate's 95%, not looser, so this does not fall foul of the prohibition on a third attempt with a looser bar.

| condition | measured | required | result |
|---|---|---|---|
| paired cluster bootstrap 97.5% CI excludes 0 | [0.00240, 0.01290] | excludes 0 | PASS |

**Overall D3b verdict: PASS**

Interval method: cluster bootstrap over 191 tournaments. Maps compared: 26830.

Excluded from scoring: 2093 maps (2093 null_team)

## Consequence

**Calibrated Glicko is a backtested strength source: the card can be built from it instead of rung 3's unverifiable public-rating divisor.** But this rests on a ONE-condition test whose other two conditions (margin, slope) were already known before this run -- it is weaker evidence than the Elo gate would have been had Elo itself passed all three conditions fresh. Building a card from Glicko is a separate decision, not made in this run.
