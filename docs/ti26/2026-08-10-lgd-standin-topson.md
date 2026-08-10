# LGD Gaming standin at TI 2026: Topson in, TaiLung banned

Owner-reported 2026-08-10, then corroborated the same day against public
reporting. This is a dated observation about the real-world roster, not a
model input: nothing in this note changes any config, rating, or card.

## The fact

Topias "Topson" Taavitsainen will stand in for LGD Gaming at TI 2026, filling
the mid role of Santiago "TaiLung" Agüero Gustavo, who was banned by PGL and
LGD over competitive-integrity issues.

Source: [GosuGamers, "Topson will stand in for LGD Gaming at The International
2026"](https://www.gosugamers.net/dota2/news/78935-topson-will-stand-in-for-lgd-gaming-at-the-international-2026),
retrieved 2026-08-10 (~06:00 UTC); the article self-dated as published 11 hours
before retrieval. Verbatim: "Topson will be filling the vacant mid laner role
left by Santiago 'TaiLung' Agüero Gustavo"; "TaiLung had been banned by PGL and
LGD Gaming due to issues of competitive integrity." The ban is separately
reported by [GosuGamers](https://www.gosugamers.net/dota2/news/78933-lgd-gaming-s-tailung-has-been-banned-from-the-international-2026-and-all-future-pgl-events)
and multiple other outlets. GosuGamers is the same class of source
`config/ti2026_teams.yaml` already cites for the field cross-check.

## What is NOT established here

- **Account ids.** This note deliberately binds no account id to either player.
  The configured LGD entry (`config/ti2026_teams.yaml`, team_id 10150538)
  records the five accounts the roster fielded; which of them is TaiLung's, and
  what Topson's account id is, are identity claims that need their own evidence
  before anyone edits a config or an alias. Do not guess them from memory.
- **Organizer-approval details.** The primary article does not state the terms
  of the substitution's approval.

## What this means for the forecast

Ratings key on the five-account roster hash. Unless LGD plays official maps
with Topson before the lock-day snapshot, the store cannot contain the standin
roster, and the card's LGD strength will derive from the roster that includes
the now-banned player. No check in the current pipeline can see this: runbook
step 4's staleness check reads the store, and the store holds match rows, not
announcements.

So on lock day this is a known model limitation to carry, not a data error to
fix silently. Three handling notes for the operator:

1. **Field is unchanged.** LGD still participates; step 3's field confirmation
   is unaffected by a player substitution.
2. **Do not edit the configured roster or add an alias** for this. A standin
   with no played maps has no rating to inherit, and inventing continuity would
   fabricate evidence. If LGD does play with Topson before the snapshot, step 4
   will surface the new account set through the store, which is the only path
   this pipeline accepts.
3. **The closing report must carry this** in its could-not-be-verified /
   limitations section: the LGD marginal is a forecast for a roster that will
   not be the one fielded.

This is exactly the roster-evidence-vs-snapshot mismatch the pre-TI hardening
slice is designed to stop on (release preflight, plan 3 of
[the hardening index](../superpowers/plans/2026-08-09-pre-ti-release-hardening-index.md)):
once evidence import exists, an owner-captured exact-five roster that differs
from the frozen model's effective snapshot roster halts the release before any
write, and shipping proceeds only by owner decision.
