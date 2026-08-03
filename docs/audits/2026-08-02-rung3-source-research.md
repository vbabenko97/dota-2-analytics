# Rung-3 source research: what's actually machine-readable

Context: `reports/d2_gate.md` (2026-08-02) recorded the elo-vs-glicko gate FAIL
and, separately, that neither model clears the spec-V floor against a
constant 50/50 prediction (elo +0.00131 nats worse, glicko +0.00514 nats
worse). Spec X rung 3 is the prescribed response: "public ratings
(Noxville/datdota) piped straight into the simulator." This audit checks
whether that source, or any alternative, is actually reachable as a
`team,strength` CSV before anyone writes ingestion code for it.

**Method note:** every network claim below was executed on 2026-08-02 from
this environment, via `.venv/bin/python -m pytest` against a throwaway probe
file (`tests/test_probe_rung3.py` / `tests/test_probe_rung3b.py`, both
deleted after use — `git status --short` on `tests/` is clean as of this
writing), or via `curl`/`WebFetch`/`WebSearch` directly. Query text and raw
output are reproduced inline rather than summarized, per the "report what the
tool printed" rule.

---

## 1. OpenDota explorer — does `teams` expose a rating?

`src/ti26/data/opendota.py` is the single existing network seam:
`explorer_query(sql, transport)` against `https://api.opendota.com/api/explorer`,
an unkeyed, public Postgres-backed SQL endpoint (confirmed by reading the
file — no auth header anywhere except a User-Agent string).

**`teams` table columns** (`select column_name, data_type from
information_schema.columns where table_name = 'teams'`):

```
team_id   bigint
name      text
tag       text
logo_url  text
```

No `rating`, `wins`, `losses`, or `last_match_time`. Selecting those columns
from `teams` fails:

```
select team_id, name, rating, wins, losses, last_match_time from teams
where team_id in (...)
→ ExplorerError: HTTP Error 400: Bad Request
```

**Isolating the cause** (comparison-with-known-difference, not just a bare
failure): the identical 16 team_ids queried for the 4 columns that *do*
exist on `teams` (`team_id, name, tag, logo_url`) return all 16 rows
successfully; `select rating from teams limit 1` alone reproduces the same
400. So the 400 is specifically "column does not exist on `teams`," not a
transport or quoting problem — **`teams` genuinely has no rating column.**

**But a sibling table does.** Searching
`information_schema.tables ilike '%rating%' or '%team%' or '%elo%'` turns up
`team_rating` (plus `team_match`, `teams`). Its columns:

```
team_id           bigint
rating            real
wins              integer
losses            integer
last_match_time   bigint
delta             real
match_id          bigint
```

This is the table backing OpenDota's public documented `/teams` REST
endpoint (`docs.opendota.com`, `GET /teams`) — confirmed by a direct
unauthenticated `curl` to `https://api.opendota.com/api/teams` on 2026-08-02:
the top row (`team_id: 9572001, rating: 1553.33, name: "TEAM VISION", ...`)
matches the explorer's `team_rating` row for the same id exactly, including
the `wins/losses/last_match_time/delta/match_id` fields the `teams` table
doesn't carry at all. So this is the same well-known public surface, not an
internal-only quirk — no new network seam is needed, only a new SQL string
against the seam that already exists.

**Coverage of our 16 teams** (`team_id in (...)` from
`config/ti2026_teams.yaml`, queried 2026-08-02):

| team_id | name | rating | games (W/L) | last match | stale (days, ref 2026-08-02) |
|---|---|---|---|---|---|
| 9572001 | Team Vision | 1553.33 | 329/172 (501) | 2026-06-25 | 37 |
| 9823272 | Team Yandex | 1527.97 | 176/119 (295) | 2026-07-19 | 13 |
| 8255888 | BoomBoys | 1479.85 | 687/531 (1218) | 2026-08-01 | 0 |
| 9247354 | Team Falcons | 1441.83 | 555/303 (858) | 2026-08-02 | 0 |
| 7119388 | Team Spirit | 1410.80 | 924/627 (1551) | 2026-07-16 | 16 |
| 9467224 | Aurora Gaming | 1360.12 | 368/270 (638) | 2026-07-15 | 17 |
| 2163 | Team Liquid | 1359.34 | 1859/1263 (3122) | 2026-08-01 | 0 |
| 726228 | Vici Gaming | 1332.07 | 1561/1061 (2622) | 2026-08-02 | 0 |
| 10150538 | LGD Gaming | 1282.52 | 38/24 (62) | 2026-08-03* | 0 |
| 2586976 | OG | 1271.65 | 1235/961 (2196) | 2026-08-03* | 0 |
| 10136357 | Nigma Galaxy | 1247.95 | 33/25 (58) | 2026-08-02 | 0 |
| 10182357 | 1win | 1236.73 | 14/9 (23) | 2026-08-03* | 0 |
| 9964962 | GamerLegion | 1230.40 | 92/92 (184) | 2026-08-03* | 0 |
| 8261500 | Xtreme Gaming | 1211.48 | 610/499 (1109) | 2026-07-14 | 18 |
| 5017210 | Team Resilience | 1207.63 | 38/39 (77) | 2026-06-18 | 44 |
| 10149530 | HULIGANI | 1183.59 | 13/8 (21) | 2026-06-28 | 34 |

\* a few `last_match_time` values land after the naive 2026-08-02 00:00 UTC
reference point because the store snapshot in `ti2026_teams.yaml` was taken
at 2026-08-02T16:55:35Z; treated as 0 days stale, not negative.

**16 of 16 configured team_ids have a non-null rating.** Mean 1333.58.
Staleness ranges from same-day to 44 days (Team Resilience) and 34 days
(HULIGANI) — both already flagged in `reports/d2_gate.md`'s roster-staleness
table as possible migrations, so the staleness here is consistent with, not
contradicting, what the pipeline already knows about those two entries.

**A real caveat, checked rather than assumed:** `team_rating` is keyed by
OpenDota `team_id`, not by roster (unlike this repo's own `EloModel`/
`GlickoModel`, which key by `roster_version_id` — see `src/ti26/roster.py`).
`config/ti2026_teams.yaml`'s own ledger documents that several of our 16
orgs are split across multiple team_ids. I checked whether that fragments
`team_rating` too, for the two documented predecessor pairs:

```
HULIGANI (configured, 10149530):        rating 1183.59, 21 games
L1GA TEAM (HULIGANI predecessor, 9303383): rating 1186.05, 734 games
Nigma Galaxy (configured, 10136357):    rating 1247.95, 58 games
Nigma Galaxy predecessor (7554697):     rating 1403.21, 1204 games
```

For the HULIGANI/L1GA TEAM pair (a documented *data duplicate* — identical
roster registered under two ids, not a real roster change, per
`ti2026_teams.yaml`), the two ratings land within 2.5 points of each other
despite a 35x sample-size difference — reassuring, though this agreement
isn't guaranteed by the mechanism, just observed here. For the Nigma Galaxy
pair (a documented *genuine* roster change, June 2026), the ratings diverge
by 155 points (≈0.89 logit units at the /400 convention) — the configured
id is roster-correct but thin (58 games). **Practical consequence:** the six
teams with under ~100 games in `team_rating` (HULIGANI 21, 1win 23, Nigma
Galaxy 58, LGD Gaming 62, Team Resilience 77, GamerLegion 184 borderline) —
which are exactly the recently-rebranded/roster-changed/newly-promoted teams
`ti2026_teams.yaml` already flags — carry a noisier estimate than the
thousands-of-games teams (Team Liquid 3122, Vici Gaming 2622, OG 2196). This
is a real weakness of this source, not a reason to reject it (no alternative
source below is even reachable), but a downstream card should treat those
six as lower-confidence.

**Conclusion for Q1: yes, machine-readable, populated 16/16, zero new
network seam required — a new SQL string against the existing
`explorer_query` seam.**

---

## 2. datdota / Noxville — machine-readable?

Background, confirmed by search: **Noxville (Ben Steenhuisen) runs/maintains
datdota** — the spec's "Noxville, datdota" names one source, not two. Their
public-facing ratings page is `datdota.com/ratings`, a Glicko-2 leaderboard.

**Access attempts, all 2026-08-02, all failed with the same signature:**

| target | method | result |
|---|---|---|
| `datdota.com/ratings` | WebFetch tool | HTTP 403 |
| `www.datdota.com/about` | WebFetch tool | HTTP 403 |
| `datdota.com/ratings` | `curl`, default UA | HTTP 403 |
| `datdota.com/ratings` | `curl`, Chrome UA + Accept/Accept-Language headers | HTTP 403 |
| `api.datdota.com/swagger-ui/index.html` | `curl` | HTTP 403 |
| `api.datdota.com/v3/api-docs` | `curl` | HTTP 403 |
| `api.datdota.com/api/ratings` | `curl` | HTTP 403 |

To rule out "our tooling specifically is blocked" rather than "the site
blocks all automation," I checked the Internet Archive's own crawler history
via the CDX API (`web.archive.org/cdx/search/cdx?url=datdota.com/ratings`):
five capture attempts in Feb–Apr 2025, **every one recorded statuscode 403**
— Archive.org's crawler gets the same wall we do. A query for any 2026
capture (`from=20260601&to=20260802`) returned zero rows: no snapshot of
this page exists at all in that window, capture-failed or otherwise.

The GitHub wiki *was* reachable (`github.com/datdota/datdota/wiki/API-Intro-&-Gotchas`,
via WebFetch): it documents that a real API exists at `api.datdota.com`
(Swagger UI, JSON/200 responses, no explicit API-key requirement mentioned),
gated by `datdota.com/terms` to non-commercial use without contacting the
maintainer first. That documentation is moot here: the API host itself
returned 403 to every request we could make against it.

**Noxville's own published dataset**
(`github.com/Noxville/glicko-dota-rank-d3-viz`, "small data collection for
Glicko 2 ratings... from datdota") — checked via the GitHub REST API
(`api.github.com/repos/Noxville/glicko-dota-rank-d3-viz`):
`created_at`, `updated_at`, and `pushed_at` are **all `2020-12-29`**; the
most recent commit (`"Fixed README."`) is dated 2020-12-29T07:29:38Z. This
repo has not been touched in over 5 years. Whatever datdota's live ratings
say today, this GitHub mirror is dead.

**Conclusion for Q2: the underlying ratings likely exist and are likely
current on the live site, but nothing about them is machine-readable from
this environment.** This isn't "requires a key" — every access path
(browser-emulating fetch, `curl` under multiple UAs, and a third-party
archival crawler) hit the same bot-protection wall with a 403, and the one
public dataset tied to the same author is a 5-year-old static snapshot. A
human with an actual browser might get through an interactive challenge;
that is out of scope for a scripted pipeline and unverified here.

---

## 3. Any other credible public source?

- **STRATZ** (`stratz.com`, GraphQL API, powers Dota2ProTracker/Overwolf):
  `stratz.com/api` also returned HTTP 403 to WebFetch on 2026-08-02. Search
  results describe a comprehensive match/player/hero-stats GraphQL API but
  surfaced **no evidence of a team-level strength/rating metric** (as
  opposed to match records, hero stats, meta stats). UNVERIFIED whether a
  team rating exists there at all, and the API is unreachable from here
  regardless — not pursued further.
- **Abios Gaming / OddsMatrix** (surfaced in search): explicitly paid B2B
  odds/data feeds requiring a commercial contract. Out of scope for a
  public, no-key rung-3 source; not investigated further.
- **Liquipedia**: publishes results, rosters, and brackets — no computed
  strength rating to extract. Not a candidate.
- **Betting-market implied probabilities**: spec X already places these at
  rung 1 ("own ratings, market-shrunk once H2H odds exist"), a different
  rung entirely, not a rung-3 substitute — out of scope for this question.

I did not exhaustively enumerate every third-party Dota stats site; I
checked the two the spec names by name (datdota/Noxville) and the one
commonly-cited comprehensive alternative (STRATZ). No other candidate
surfaced in search results as a credible, independent team-strength rating.

**Conclusion for Q3: no additional viable source found.**

---

## 4. Scale conversion

| source | scale | conversion recommendation |
|---|---|---|
| OpenDota `team_rating.rating` | Empirically Elo-shaped: our 16 range 1183.6–1553.3, mean 1333.6; global top-10 sample (queried same day) tops out ~1553, consistent with a base-1500 Elo system. **Not documented** by OpenDota in any reachable doc (`docs.opendota.com` also 403'd on 2026-08-02). The sibling `player_computed_mmr` rater (`svc/rater.ts` in `odota/core`, fetched from `raw.githubusercontent.com` on 2026-08-02) uses classic Elo with `10 ** (rating/400)`, K=50, default 4000 — a *different* table, not `team_rating` itself; I could not locate the specific source file that writes `team_rating` (checked the full `svc/` directory listing via the GitHub contents API — no `teamRating`/`teamRanks`/`elo`-named file; GitHub's code-search API requires auth (401) so a full-repo grep wasn't possible unauthenticated). | Treat as Elo-scale by convention (same divisor our own code already uses): `logit_per_elo = math.log(10) / 400` (matches `src/ti26/ratings/elo.py`'s `LOGIT_PER_ELO`, and the sibling MMR system's confirmed divisor), then zero-center by subtracting the **mean over our 16 teams** (not OpenDota's global population, since the card is scoped to these 16). **Flagged explicitly: the /400 divisor is an inference from convention + a sibling system, not a documented constant for this specific table.** |
| datdota/Noxville Glicko-2 | Standard Glicko-2 (mean ~1500 by Glickman's convention, own internal mu/phi scale uses a `173.7178` constant, separate from the classic Elo /400 logistic). Not independently verified here — inaccessible, so no actual data point was fetched. | Moot: cannot convert data we cannot fetch. |
| STRATZ | No known team-rating field found. | N/A |

---

## 5. Team-name mapping

- **OpenDota**: keyed by the same numeric `team_id` already resolved and
  curated (with extensive rebrand/duplicate-id provenance) in
  `config/ti2026_teams.yaml`. Zero new mapping cost — join on `team_id`,
  emit that file's `name` field as the CSV's `team` column, exactly the key
  the rest of the pipeline already uses.
- **datdota/Noxville**: keyed by their own team name strings (as seen in
  Noxville's public rating posts). This would need a real name-reconciliation
  pass against our 16 org names — the same class of cost this repo's own
  `team_aliases.yaml`/`ti2026_teams.yaml` ledgers already document at length
  for OpenDota's own id churn (rebrands, sponsor-name changes, gambling-
  sponsorship renames like BetBoom→BoomBoys). Moot here since the source
  itself is unreachable, but worth naming: it is not a free mapping even if
  access were solved.

---

## Bottom line

**OpenDota's own `team_rating` table is the only source in this survey that
is both machine-readable and reachable from this environment, right now.**
datdota/Noxville — the source spec X actually names — is blocked by
bot-protection on every access path tried (browser-emulating fetch, `curl`
under multiple UAs, and even the Internet Archive's crawler), and the one
public dataset tied to the same author has been dead since 2020. STRATZ is
similarly unreachable and has no confirmed team-rating field. No other
credible public source surfaced.

Recommendation: build the rung-3 CSV from OpenDota's `team_rating` table via
a new `explorer_query` SQL string (no new network seam), joined on `team_id`
from `config/ti2026_teams.yaml`, converted with
`logit_per_elo = math.log(10) / 400` and zero-centered over our 16 teams —
while flagging the six thin-sample teams (HULIGANI, 1win, Nigma Galaxy, LGD
Gaming, Team Resilience, GamerLegion) as lower-confidence in whatever report
consumes this CSV, since their `team_rating` sample sizes are an order of
magnitude smaller than the rest of the field.
