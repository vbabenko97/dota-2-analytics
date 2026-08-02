import pytest

from ti26.data.schema import RosterSlotError, normalize_all, normalize_row

RADIANT_SLOTS = [0, 1, 2, 3, 4]
DIRE_SLOTS = [128, 129, 130, 131, 132]


def raw(**overrides):
    row = {
        "match_id": 8925460065,
        "start_time": 1785661502,
        "duration": 2555,
        "radiant_win": True,
        "leagueid": 20009,
        "tier": "professional",
        "radiant_team_id": 10136357,
        "dire_team_id": 2586976,
        "series_id": 1126703,
        "series_type": 1,
        "patch": "7.41",
        "accounts": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "heroes": [11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
        "slots": RADIANT_SLOTS + DIRE_SLOTS,
    }
    row.update(overrides)
    return row


def test_roster_split_follows_slots_not_positional_assumption():
    row = normalize_row(raw())
    assert row.radiant_accounts == (1, 2, 3, 4, 5)
    assert row.dire_accounts == (6, 7, 8, 9, 10)


def test_out_of_order_slots_still_split_correctly():
    """array_agg ordering is a database guarantee we decline to trust blindly.

    Feeding deliberately shuffled slots proves the split reads `slots`
    rather than slicing [0:5] and hoping.
    """
    order = [128, 0, 129, 1, 130, 2, 131, 3, 132, 4]
    accounts = [106, 101, 107, 102, 108, 103, 109, 104, 110, 105]
    row = normalize_row(raw(slots=order, accounts=accounts, heroes=list(range(10))))
    assert row.radiant_accounts == (101, 102, 103, 104, 105)
    assert row.dire_accounts == (106, 107, 108, 109, 110)


@pytest.mark.parametrize(
    "slots",
    [
        [0, 1, 2, 3, 4, 128, 129, 130, 131],          # nine players
        [0, 1, 2, 3, 4, 5, 128, 129, 130, 131],       # six radiant
        [0, 0, 1, 2, 3, 128, 129, 130, 131, 132],     # duplicate slot
    ],
)
def test_malformed_rosters_raise(slots):
    with pytest.raises(RosterSlotError):
        normalize_row(raw(slots=slots, accounts=list(range(len(slots))),
                          heroes=list(range(len(slots)))))


def test_series_type_maps_to_best_of():
    assert normalize_row(raw(series_type=0)).best_of == 1
    assert normalize_row(raw(series_type=1)).best_of == 3
    assert normalize_row(raw(series_type=2)).best_of == 5


def test_unknown_series_type_falls_back_to_one_map_not_a_crash():
    """series_type 3 appears in real data (171/3011 in the sampled month).

    OpenDota does not document it. Treating it as a single map is a stated
    assumption, not a silent guess: `best_of` is only used for reporting,
    never for rating updates, which are per-map.
    """
    assert normalize_row(raw(series_type=3)).best_of == 1
    assert normalize_row(raw(series_type=None)).best_of == 1


def test_null_team_id_is_flagged_not_dropped():
    row = normalize_row(raw(dire_team_id=None))
    assert row.has_null_team is True
    assert row.match_id == 8925460065, "the row survives; only the flag changes"


def test_null_account_in_roster_is_flagged_not_dropped():
    row = normalize_row(raw(accounts=[1, 2, 3, 4, None, 6, 7, 8, 9, 10]))
    assert row.has_bad_roster is True
    assert row.match_id == 8925460065, "the row survives; only the flag changes"


def test_normalize_all_counts_rejections_instead_of_discarding_silently():
    good = raw()
    bad = raw(match_id=1, slots=[0, 1, 2, 3, 4, 128, 129, 130, 131],
              accounts=list(range(9)), heroes=list(range(9)))
    rows, tally = normalize_all([good, bad])
    assert len(rows) == 1
    assert tally == {"roster_slot_error": 1}, "every dropped row is accounted for"


def test_normalize_all_tallies_a_missing_key_as_malformed_row():
    good = raw()
    bad = raw(match_id=2)
    del bad["slots"]
    rows, tally = normalize_all([good, bad])
    assert [r.match_id for r in rows] == [8925460065]
    assert tally == {"malformed_row": 1}


def test_normalize_all_tallies_a_non_numeric_duration_as_malformed_row():
    good = raw()
    bad = raw(match_id=2, duration="not-a-number")
    rows, tally = normalize_all([good, bad])
    assert [r.match_id for r in rows] == [8925460065]
    assert tally == {"malformed_row": 1}


def test_accounts_are_hashable_tuples_for_roster_keying():
    row = normalize_row(raw())
    assert isinstance(row.radiant_accounts, tuple)
    hash(row.radiant_accounts)  # must not raise — Task 3 hashes these
