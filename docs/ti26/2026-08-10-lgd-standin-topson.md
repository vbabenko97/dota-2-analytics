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

## Account ids, resolved 2026-08-11 through the explorer seam

The owner authorized resolving these rather than supplying them. They were read
from OpenDota's curated `notable_players` table through `explorer_query`, the
project's only network path — the same class of resolution
`config/ti2026_teams.yaml` used for team ids. They were not recalled from
memory and none was invented.

| player | account id | `notable_players` country | owner's list |
|---|---|---|---|
| TaiLung | 1026694469 | pe | (absent — replaced) |
| Topson | 94054712 | fi | Finland |
| Yuma | 177203952 | af | Nicaragua |
| Wisper | 292921272 | bo | Bolivia |
| Thiolicor | 105045291 | br | Brazil |
| KJ = KingJungles | 81306398 | br | Brazil |

The five ids above other than Topson's are exactly the configured LGD roster,
so the substitution is unambiguous: **remove 1026694469, add 94054712.**

Two identification cautions, recorded rather than smoothed over. OpenDota
carries two further accounts named `topson` and `TOPSON`, registered to
ProstoServak Team and Novus; neither is this player. And `notable_players`
gives Yuma's country as `af`, which contradicts the owner's list — an upstream
data quirk that does not affect the account set, since Yuma's id was already
configured and is unchanged.

`notable_players` still lists Topson's registered team as Tundra Esports. That
field lags roster moves and is not evidence of who he plays for now; the
substitution rests on the reporting cited above, not on it.

## What is NOT established here

- **Organizer-approval details.** The primary article does not state the terms
  of the substitution's approval.
- **Any rating for the standin roster.** See the next section: the account set
  containing 94054712 has never played a map in this corpus.

## The standin roster has no history in the committed store

Checked 2026-08-11 against `data/processed/release-20260802T165535Z.sqlite`,
the store the pinned snapshot builds: **no map fields the exact standin five,
and no map fields Topson's account alongside any current LGD account.** Both
are counts of zero, so there is nothing here to bind or restate. Topson's own
maps in this store are under a different team id entirely, and none is recent
relative to the snapshot.

That makes the consequence below concrete rather than hypothetical: the standin
roster hash is a cold start. It has no rating to inherit and no continuity to
claim, and manufacturing either would be fabrication.

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
