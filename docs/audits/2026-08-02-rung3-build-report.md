# Superseded: rung-3 public-ratings build report

This document no longer publishes results in the current tree. Its public-rating
strengths, sensitivity sweep, ordering anchor and drift observations had no
committed producer binding them to an input.

They are also not regenerable offline. `ti26.cli_rung3` reads OpenDota's live
`team_rating` table through the project's single network seam, and that table has
no snapshot in this repository: a rerun today would fetch different numbers and
could not reproduce the ones this report carried. They are withdrawn rather than
restated.

The module itself is unchanged and remains the documented rung-3 fallback. Its
causal prose has been narrowed to what it computes -- the deviation summary counts
Wilson-flag directions and now says plainly that it cannot attribute a cause, and
the thin-history flag is described as the sample-size flag it is rather than a
measured Elo bias.

See [the correction register](2026-08-04-correction-register.md). The prior
narrative remains in Git history.
