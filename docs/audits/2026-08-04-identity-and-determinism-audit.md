# Identity re-verification and a determinism defect (2026-08-04)

Prompted by the project owner supplying the authoritative TI-facing name list
(old org -> TI name). The intent was a name check. It found one wrong display
name, confirmed every team_id, and then -- by accident, while fixing the name --
exposed a defect that had been silently deciding the card's most extreme slot.

## 1. Identity verification: 16 of 16 correct

Method: compare ACCOUNT SETS against the store, never names. Names were used
only to look up candidate ids remotely; every conclusion below rests on the
five account ids a roster actually fielded. The local store carries no team
names at all, so the remote `teams` table was queried once for candidate ids.

| owner's mapping | verdict |
|---|---|
| Aurora, Falcons, Liquid, Yandex, Xtreme, Spirit, Nigma, Vici, Resilience | already correct |
| BetBoom -> BoomBoys | already correct (8255888) |
| L1ga Team -> Huligani | already correct (10149530) |
| Heroic -> LGD Gaming | already correct (10150538), 5/5 continuity |
| PARIVISION -> Team Vision | correct, renamed in place -- see below |
| Apex Genesis -> GamerLegion | correct, predecessor chain intact -- see below |
| OG (new SEA roster) | correct, chains through the SEA side -- see below |
| Tundra -> 1win -> **Iron Wing** | **display name was WRONG**, fixed |

**PARIVISION -> TEAM VISION (9572001).** Renamed in place; no separate
PARIVISION id exists (a remote `%pari%` search returns only unrelated teams).
The org does have a second id, 9824702 "PVISION", which an org-name search
cannot match -- found by the staleness detector instead (section 1a). Counting
per ROSTER across every team_id that fielded it, the chain is 282 maps
(2025-02-16 -> 2026-01-05) -> 97 -> the current 80, each successor sharing 4/5
accounts with its predecessor, and `RosterIndex` resolves it without an alias
because 9572001 saw the current roster first (2026-05-08 vs 9824702's
2026-05-26). Verified by walking the fitted index. The best-supported chain in
the field, which matters because this entry holds the card's 4-0 slot.

An earlier version of this section gave that chain as "237 -> 97 -> 80", which
mixed one team_id-scoped count (237 maps under 9572001) into two rvid totals.
That is the same mixed-population error already recorded twice in
`config/ti2026_teams.yaml` against the Nigma and Tundra entries, made a third
time by the same author and caught by the reconciliation in section 1a rather
than by re-reading.

**Apex Genesis -> GamerLegion (9964962).** The 267-map Apex Genesis roster
`77aa9436a6f28e94` was fielded by team_id 9964962 itself for 86 of those maps
(2025-11-15 -> 2026-02-20) before two single-player swaps produced the current
`8f07578dc483e1ae`. `RosterIndex` chains predecessors by the team's own roster
sequence, so the Apex Genesis prior propagates with no alias needed.

**OG (2586976).** The 2025-11-08 SEA signing is visible as a clean 5/5 break:
`b6807127ad482080` ends 2025-10-21, `cea28836f2f70903` begins 2025-11-15
sharing ZERO accounts. The current roster (27 maps, the thinnest in the field)
chains back through `ededc1aba09e25f0` to that SEA roster's 109 maps, so its
prior comes through the SEA side and never through the discarded EU roster.

**Iron Wing.** Rating impact of the rename: NONE. All three ids carry the
identical roster `e0492e01c08d07f5` -- 8291895 (189 maps) + 10150413 (24) +
10182357 (21) = 234 -- and ratings key off that hash, never off team_id or
display name. Note OpenDota's per-id labels do not agree with the real
chronology (the MIDDLE id is the one labelled "Iron Wing"), so those labels
are not evidence about the current name and were not used as such.

## 1a. Duplicate ids: the detector beat the manual pass

Two new duplicate ids were found by hand (10208009 "L1GA TEAM", 10207984 "Team
resilience", both registered after 2026-08-02). Running
`teams.check_roster_staleness` afterwards -- the detector built for exactly this
-- reported those two plus **two the manual pass had missed**:

| configured team | second id | maps under it | span | verdict |
|---|---|---|---|---|
| HULIGANI | 10208009 | 6 | 07-31 -> 08-01 | duplicate, same rvid |
| Team Resilience | 10207984 | 8 | 07-31 -> 08-02 | duplicate, same rvid |
| Xtreme Gaming | **10208071** | 5 | 07-31 -> 08-01 | duplicate, same rvid |
| Team Vision | **9824702 "PVISION"** | 75 | 2025-07-08 -> 2026-07-19 | duplicate, same rvid |
| LGD Gaming | 10208068 "LGD.Pinghu" | 6 | 07-31 -> 08-01 | duplicate, already documented |

Four of the five appeared in a single burst on 2026-07-31, which reads like an
OpenDota-side re-registration rather than four independent org events.

All confirmed duplicates by direct account comparison, so every rating already
includes these maps and no alias or config change is needed. Two lessons worth
keeping:

1. The detector earned its place. An org-name search cannot match "PVISION" to
   "Team Vision", and 9824702 predates the 2026-08-02 pass -- it was missed by
   name-based checking twice before an account-keyed check found it.
2. Four configured teams are LESS idle than their own ids suggest: HULIGANI,
   Team Resilience, Xtreme Gaming and Team Vision kept playing under a second
   id past 2026-06-28, 2026-06-18, 2026-07-14 and 2026-06-25 respectively.

## 2. The determinism defect

Renaming "1win" to "Iron Wing" changed no strength -- identical slope (0.4023)
and identical spread (1.8518 -> 0.7450), max strength delta 0.0005 -- yet it
moved the card's 0-4 slot from Team Resilience to GamerLegion and raised the
count of seed-unstable slots from 2 to 5.

**Mechanism.** `run_swiss` sorted its team ids before every RNG draw it made
(`swiss.py:70` for the initial groups, `swiss.py:23` and `swiss.py:118` for the
schedules). Those ids were display names, so alphabetical position determined
which team consumed which random draw. "1win" sorted first; "Iron Wing" sorts
seventh. Every simulation shifted. `optimize.py`'s row order broke solver ties
by name for the same reason.

**Why it changed the answer.** The two candidate assignments were **4.2e-4**
expected points apart, while a single marginal carried **6.5e-4** of Monte
Carlo standard error at 250,000 sims. The solver was ranking assignments it
could not resolve, so an RNG reshuffle was enough to flip the outcome. The
card's most extreme slot was being decided by simulation noise.

**Fixes.**

1. `montecarlo.canonical_labels` relabels teams to strength-ranked internal
   ids (`t00`-style) before simulating and maps back afterwards. One boundary
   change covers all three ordering sites. Zero-padding keeps lexicographic
   order equal to rank order, so downstream `sorted()` calls need no edits.
2. `optimize.solve_card` gained `tie_tolerance`: assignments within one Monte
   Carlo standard error of the optimum count as tied, and the tie is settled by
   a stated rule -- a scarce category goes to whoever is most likely to land
   there (each marginal weighted by 1/capacity, so the one-wide 4-0 and 0-4
   slots outrank the five-wide pools). Row order is now keyed on the marginal
   vector, not the name.

A first attempt at fix 2 quantized each marginal to the standard error. That
was a no-op and was discarded: the cells making up two near-tied totals differ
from each other by far more than the error (0.148 vs 0.122), so they survive
rounding untouched. It is the assignment TOTALS that must be compared at the
tolerance, which is what the shipped implementation does.

**Verification.** 681 passed (676 before, +5), ruff clean. Both new tests were
mutation-checked rather than merely observed to pass:

| mutant | result |
|---|---|
| `canonical_labels` returns identity (pre-fix behaviour) | rename test FAILS |
| `_break_ties` returns input unchanged | tie-break test FAILS |
| tolerance bound removed so the rule always fires | 2 tests FAIL |

**Result.** The card is now identical to the pre-rename card with "Iron Wing"
relabelled, and **0 of 16 slots are seed-unstable**, down from 5. The tie-break
cost 0.000048 expected points this run against its 0.001 tolerance, and moved
only BoomBoys and Team Falcons between 4-1 and elim_win.

**What this does NOT mean.** Seed stability is not certainty. The fix stops the
assignment procedure amplifying Monte Carlo noise into slot flips; it does
nothing about the uncertainty in the strengths themselves, which still carry
RDs of 46 to 79 rating points that the card has no way to express. A stable
card and a confident card are different claims.

## 3. Team Resilience and the 0-4 slot

The owner flagged Resilience as a possible dark horse: no international
matches, qualified via its home region. The data supports the premise.

| metric | Team Resilience | rest of field |
|---|---|---|
| rating | 1745.0 (lowest) | up to 2066.7 |
| RD | 78.7 (highest) | 45.9 - 75.5 |
| maps | 38 | 27 - 376 |
| mean opponent rating | **1622.4** | 1727.2 - 1889.3 |
| mean opponent RD | **110.3** | 52.9 - 79.7 |
| win rate | 0.684 | 0.515 - 0.762 |

Its 38 maps span 4 leagues against 15 opponents, 13 of whom have 22 maps or
fewer in the entire store. Contrast OG (27 maps) and Nigma (30 maps): equally
thin, but their opposition averages 1817 and 1870 at normal RD, so they are
anchored in the right range. Resilience is the only team off the anchor.

**Two hypotheses tested and rejected.**

*Prior artifact.* Every team sits above the 1500 prior (+245 to +567), which
suggested the ranking might partly reflect how far each team had been pulled
off the prior. Refitting at initial ratings 1500 / 1700 / 1900 translates all
16 by exactly +200 / +400 with zero rank change and zero gap change: the system
is translation-invariant, so "distance above prior" is not a meaningful
quantity and the 0-4 slot does not depend on the prior level.

*Un-discounted weak opposition.* `glicko.py:107-110` already attenuates each
update by the opponent's RD (`g_j` scales both the information term and the
delta), so Resilience's wins over RD-110 opponents already moved its rating
less than the same wins over well-measured opponents would have. 1745 is the
properly-discounted posterior. Shrinking it toward the field mean would
double-count a discount Glicko already applied.

**What remains** is irreducible: the TI field averages 1899 and Resilience's
opposition averages 1622, so every prediction about it extrapolates roughly 277
rating points beyond any game this roster has played. The logistic model is an
assumption out there, not a measurement, and the extrapolation has no known
direction -- it could be too harsh or too kind.

Also recorded against the "form ABOVE implied" flag it carries: 5 of 16 teams
carry that flag and 0 are below, because observed form counts non-TI opponents.
Resilience has the field's weakest opposition and therefore the largest upward
bias in that diagnostic. The flag is expected there, not informative.

**Decision (owner's, 2026-08-04): keep the model's assignment.** Moving the
slot to HULIGANI would have cost 0.0025 expected points (to GamerLegion,
0.0012) and bought robustness against the extrapolation, but Glicko's discount
is already correct and the residual risk is directionless, so an override would
be a coin flip presented as insight. Recorded here so the reasoning survives
the outcome either way.

## 4. Card as shipped

Expected score 4.628996 against a random baseline of 3.75. Seed 1, 250,000
sims, 0 of 16 slots seed-unstable.

| category | teams |
|---|---|
| 4-0 | Team Vision |
| 4-1 | BoomBoys, Team Yandex |
| elim_win | Aurora Gaming, Nigma Galaxy, Team Falcons, Team Liquid, Team Spirit |
| elim_loss | Iron Wing, LGD Gaming, OG, Vici Gaming, Xtreme Gaming |
| 1-4 | GamerLegion, HULIGANI |
| 0-4 | Team Resilience |

The gate lineage behind this card is unchanged and remains qualified: D2's
forecast-value gate FAILED, D3's Elo gate FAILED on all three conditions, and
D3b passed as a ONE-condition test whose slope cleared its band by 0.0049. See
`reports/card_provenance.md` and the D3 calibration report.
