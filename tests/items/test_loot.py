"""The loot extractors, one test per spec scenario in scholar-loot. Packets are given as decoded fields."""

from conftest import MEMBER, MOB, PLAYER, STRANGER, claim, drive

from ffxi_extractors.combat import P
from ffxi_extractors.extractors.battle.kills import Kills
from ffxi_extractors.extractors.items.drops import Drops
from ffxi_extractors.extractors.items.obtained import Obtained


def defeat(by, message=6):
    return 0x029, {"UniqueNoCas": by, "UniqueNoTar": MOB, "ActIndexTar": 0x010, "MessageNum": message}


def treasure_hunter(level):  # a melee hit whose added effect raises Treasure Hunter
    return 0x028, {
        P + "actor_id": PLAYER, P + "target_count": 1, P + "targets[0].target_id": MOB,
        P + "targets[0].result_count": 1, P + "targets[0][0].message": 1, P + "targets[0][0].value": 30,
        P + "targets[0][0].proc.message": 603, P + "targets[0][0].proc.value": level,
    }  # fmt: skip


def test_a_party_kill():
    (k,) = drive(Kills, claim(MEMBER), claim(0), defeat(PLAYER))["kills"]
    assert (k["mob_id"], k["killer_id"], k["claim_id"], k["claimed_by_party"]) == (MOB, PLAYER, MEMBER, True)


def test_a_despawn_ends_the_claim_and_treasure_hunter():
    """The mob may die and respawn out of view: its next defeat is a new life's."""
    despawn = (0x00E, {"UniqueNo": MOB, "ActIndex": 0x010, "SendFlg.Despawn": 1})
    (k,) = drive(Kills, claim(PLAYER), treasure_hunter(4), despawn, defeat(STRANGER))["kills"]
    assert (k["claim_id"], k["claimed_by_party"], k["th_level"]) == (None, None, None)


def test_someone_elses_kill():
    (k,) = drive(Kills, claim(STRANGER), defeat(STRANGER))["kills"]
    assert (k["killer_id"], k["claimed_by_party"]) == (STRANGER, False)


def test_treasure_hunter_goes_up():
    kills = drive(Kills, treasure_hunter(2), treasure_hunter(4), treasure_hunter(3), defeat(PLAYER),
                  defeat(PLAYER, 20))["kills"]  # fmt: skip
    assert [(k["th_level"], k["killer_id"]) for k in kills] == [(4, PLAYER), (None, None)]


ENTRY = {"TrophyItemNo": 1050, "TrophyItemNum": 1, "TargetUniqueNo": MOB, "TargetActIndex": 0x010,
         "TrophyItemIndex": 0, "StartTime": 1_777_000_000}  # fmt: skip


def result(judge, lot=0):
    return 0x0D3, {"TrophyItemIndex": 0, "JudgeFlg": judge, "LootUniqueNo": MEMBER, "sLootName": "Friend",
                   "LootPoint": lot}  # fmt: skip


def test_a_coffer_key_drops():
    entry = ENTRY
    (d,) = drive(Drops, (0x0D2, entry), result(0, 412), (0x0D2, entry), (0x0D2, {"TrophyItemNo": 0}),
                 result(1, 412), (0x0D2, entry), result(2))["drops"]  # fmt: skip
    assert (d["item_id"], d["mob_id"], d["slot"], d["start_time"]) == (1050, MOB, 0, 1_777_000_000)
    won = ("won", MEMBER, "Friend", 412)
    assert (d["outcome"], d["winner_id"], d["winner_name"], d["winning_lot"]) == won
    assert (d["ts_ms"], d["settled_ms"], d["settled_idx"]) == (0, 4000, 4)  # it left the pool at the result


INV, SATCHEL, BIN = 0, 5, 17


def put_slot(c, i, item, n, op=0x020):
    return op, {"Category": c, "ItemIndex": i, "ItemNo": item, "ItemNum": n}


def obtained(*timed):
    """timed: (ms, step). After a zone-in the server sends the inventory and the satchel whole."""
    held = [put_slot(INV, 0, 0xFFFF, 1000), put_slot(INV, 1, 4098, 5)]  # gil, 5 wind crystals
    load = [(0x00A, {"ZoneNo": 0x0A3}), *held, (0x01D, {"Flags": 1}), put_slot(SATCHEL, 1, 1050, 1),
            (0x01D, {"Flags": 1 | 1 << SATCHEL})]  # fmt: skip
    steps = [*held, *load, *(s for _, s in timed)]
    times = [0] * (len(held) + len(load)) + [t for t, _ in timed]
    return [(r["idx"], r["item_id"], r["quantity"], r["source"], r["event_idx"])
            for r in drive(Obtained, *steps, times=times)["obtained"]]  # fmt: skip


def test_what_the_character_held_is_not_obtained():
    """The capture's start and every zone-in send the inventory again: none of it is new."""
    assert obtained() == []


def test_an_item_into_an_empty_slot_or_a_bigger_stack():
    more = (0x01E, {"Category": INV, "ItemIndex": 1, "ItemNum": 8})
    got = obtained((5000, put_slot(INV, 2, 2861, 1)), (9000, more))
    assert got == [(8, 2861, 1, None, None), (9, 4098, 3, None, None)]


def test_a_move_a_sort_gil_or_a_drop_is_not_obtained():
    got = obtained(
        (5000, put_slot(INV, 1, 0, 0)), (5000, put_slot(SATCHEL, 2, 4098, 5)),  # to the satchel
        (9000, put_slot(SATCHEL, 1, 0, 0)), (9300, put_slot(INV, 7, 1050, 1)),  # back, a tick later
        (12000, put_slot(INV, 0, 0xFFFF, 5000)),  # gil
        (15000, put_slot(INV, 7, 0, 0)), (15000, put_slot(BIN, 1, 1050, 1)),  # dropped
    )  # fmt: skip
    assert got == []


def test_a_reward_after_a_zone_in_cutscene_follows_it():
    """A zone-in that plays a cutscene starts an event, as events and keyitems read it; obtained did not."""
    every = (0x01D, {"Flags": 1 | 1 << SATCHEL})
    got = obtained((5000, (0x00A, {"ZoneNo": 0x0A3, "EventNum": 1, "EventPara": 100})), (5000, every),
                   (6000, put_slot(INV, 2, 13014, 1)))  # fmt: skip
    assert got == [(10, 13014, 1, None, 8)]


def test_an_item_taken_back_out_of_the_recycle_bin_is_not_obtained():
    """The bin was left out, so a drop was no loss but taking the item back was a gain."""
    got = obtained(
        (5000, put_slot(INV, 1, 0, 0)), (5000, put_slot(BIN, 1, 4098, 5)),  # dropped
        (9000, put_slot(BIN, 1, 0, 0)), (9000, put_slot(INV, 1, 4098, 5)),  # taken back
    )  # fmt: skip
    assert got == []


def test_a_pool_win_and_a_quest_reward():
    """A pool win is its drop's row already; a reward follows the NPC's event."""
    win = (0x0D3, {"TrophyItemIndex": 0, "JudgeFlg": 1, "LootUniqueNo": PLAYER})
    got = obtained((5000, (0x0D2, ENTRY)), (6000, win), (6000, put_slot(INV, 2, 1050, 1)),
                   (20000, (0x032, {})), (25000, put_slot(INV, 3, 13014, 1)))  # fmt: skip
    assert got == [(10, 1050, 1, "pool", None), (12, 13014, 1, None, 11)]
