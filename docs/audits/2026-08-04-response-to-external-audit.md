# Response to the external audit of `d0221dc`

> **Retained verbatim as a source record, not as current results.** This is the
> triage that turned [the external audit](2026-08-04-external-audit-of-d0221dc.md)
> into the work plan for this branch, kept unedited so the reasoning behind each
> accepted and contested finding stays legible. It describes the tree at
> `d0221dc`. What was actually done about each finding is in
> [the correction register](2026-08-04-correction-register.md) and the outcome
> table of [the closing report](2026-08-04-reproducibility-closing-report.md).

This report is good, and its central criticism lands. Short version: my results held up; my claims about having verified them did not.

What it got right that I got wrong
1. The name-independence claim is false as stated. I wrote that the card "provably cannot depend on team display names" and put that in a commit message. It depends on display names whenever two strengths are exactly equal — canonical_labels falls back to (-strength, name), and optimize.py does the same for byte-identical marginal rows. I documented that fallback as harmless ("the teams are interchangeable and the choice cannot matter") on reasoning, not measurement. The auditor executed a counterexample and eight marginal rows moved. Practical impact on the real card is near zero — float strengths from a Glicko fit don't tie — but "provably cannot" was an overclaim and no test covers the tie case.

2. The tie tolerance is not the standard error I said it was. This is the best finding in the report. I pass monte_carlo_stderr(0.5, n) — the SE of one marginal. The quantity actually being compared is a difference of sums of 16 correlated marginals. Those are not the same number, and I never derived the one I needed. It's a heuristic of roughly the right magnitude with a justification written as though it were exact.

3. Four numbers in the D4 audit have no producer in the repo. The sim-count sweep, the 200k random-card control, the naive ladder, the rank correlation — I computed all of them in throwaway inline commands. Nothing committed reproduces any of them. That is precisely the defect class this repo has documented four times, and I committed a fifth batch of it inside the document that warns about it. The auditor independently recomputed +0.375 / 1 / 10 / 5 and got my numbers, so they're true — but "true and unbound to code" is exactly the failure mode, because the next run can't check them.

4. cli_d4.py hardcodes 0.4023 as the production comparator, in a file whose whole point was to avoid a stale hardcoded slope. cli_card was careful about this; I wasn't.

5. cli_d4.py has zero tests. I wrote 26 for observed.py and 3 for card_score_distribution, then never tested the runner that wires them together. The auditor's point is sharp: the entire pipeline from line 54 could be hardcoded and all 710 tests would still pass.

6. "Model expected" means two different things in my write-up — 4.1675 is the solver's marginal objective, 4.1634 is the independent evaluation-sim mean. I used the first in the headline and the second in the console line.

The one verdict I'd contest
Claim 4. The auditor marks "one-condition test" REFUTED because cli_d3b computes a three-way conjunction. That's true of the control flow, and I never claimed otherwise — the spec says so explicitly. My claim was epistemic: margin and slope were already measured and already passing before that gate ran, so only the interval was genuinely at risk. The auditor's own note confirms that ("earlier tracked D3 output shows margin/slope existed before D3b code"). So the substance stands; what it correctly exposes is that my phrasing invites a control-flow reading. Its accompanying point — that registration timing isn't provable from code — is fair and unavoidable.

Why I trust the report
It reproduced the uncomfortable results by fresh execution rather than just agreeing with me: the failed D2 gate, the failed Elo gate, the 1/16 D4 score, the leakage boundary, 710 tests, ruff clean. An audit that confirmed only the flattering claims would be worth less.

Net: the forecasting conclusions survive — including the negative ones, which are the load-bearing ones. What doesn't survive is the reliability of my self-reporting on verification, in a consistent direction: I asserted properties from reasoning and wrote them down as if measured.

Haven't touched anything. The fixes I'd rank as worth doing, in order: commit a real producer for the four D4 numbers (or delete the claims), derive or replace the tie tolerance, add test_cli_d4.py with an exact-cutoff row, then correct the two overclaimed comment blocks. Say which of those you want.