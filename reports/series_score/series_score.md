# S1: series-level scoring on TI 2025

Registered in `docs/ti26/2026-08-08-ti2025-series-scoring-spec.md` before this producer existed. **Diagnostic: no threshold, gates nothing, cannot alter the card.**

Training window 44,097 maps over 539.9 days (17.7 months), strictly before the 1756944000 cutoff. Calibration slope refit on those rows only: 0.4352.

| population | n | accuracy | one-sided p | Brier | vs 0.5 | log loss | vs 0.5 | calib. slope |
|---|---|---|---|---|---|---|---|---|
| all TI 2025 | 58 | 0.621 | 0.0435 | 0.2147 | 0.2500 | 0.6182 | 0.6931 | 2.1165 |
| Swiss stage | 44 | 0.591 | 0.1456 | 0.2114 | 0.2500 | 0.6108 | 0.6931 | 2.1322 |
| playoffs | 14 | 0.714 | 0.0898 | 0.2249 | 0.2500 | 0.6418 | 0.6931 | 2.2418 |

A calibration slope of 1.0 is perfect. Below 1.0 is overconfidence -- the model saying 65% where the truth is 80% -- which is the specific failure the design spec named.

**The playoff row is the weakest line in this table and was registered as a subgroup for that reason.** At n=14 the model needs 11 correct to beat a coin flip at one-sided p<0.05, which a genuinely 65%-accurate model reaches only 22% of the time. It is reported because it was named in advance, not because it can settle anything.

Excluded for missing strengths: 0.

All 58 series share a patch, a venue, a meta and a field, so they are not 58 independent draws and the effective sample is smaller than 58 by an amount this producer does not estimate.
