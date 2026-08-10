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

What that means operationally depends on which pipeline runs on lock day:

- **Under the current pipeline** (pre-hardening), nothing stops the release:
  the card ships with the stale-roster LGD marginal, and the closing report
  must carry that in its could-not-be-verified / limitations section.
- **Once plan 3 of
  [the hardening index](../superpowers/plans/2026-08-09-pre-ti-release-hardening-index.md)
  is implemented and exact-roster evidence is imported, this is a preflight
  FAILURE, not a report footnote.** An owner-captured exact-five LGD roster
  containing Topson will not equal the snapshot roster containing TaiLung, and
  preflight halts the release before any store, bundle, or registry write.
  That stop is the designed behavior. Getting past it requires a recorded
  owner decision among: retain the stop and do not publish that release;
  explicitly reauthorize a pre-hardening fallback path; authorize a predictive
  cold-start change for the standin roster; or defer plan 3 enforcement until
  after the TI 2026 card. Quietly capturing roster evidence that names
  TaiLung's account because it already exists would falsify the evidence, not
  resolve the mismatch.

Handling notes for the operator either way:

1. **Field is unchanged.** LGD still participates; step 3's field confirmation
   is unaffected by a player substitution.
2. **Do not edit the configured roster or add an alias** for this. A standin
   with no played maps has no rating to inherit, and inventing continuity would
   fabricate evidence. If LGD does play official maps with Topson before the
   snapshot, step 4 will surface the new account set through the store, which
   is the only path the current pipeline accepts.
