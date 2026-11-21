"""The character's status effects (0x063 type 9 beside 0x028), its defeats, and the items it and its party
used. Packets are given as decoded fields."""

from conftest import MEMBER, PLAYER, drive
from fill import put

from ffxi_extractors.extractors import Defeats, Effects
from ffxi_extractors.extractors.combat import P
from ffxi_extractors.extractors.effects import EPOCH_S, WRAP, expiry_ms

T0 = 1_792_000_000_000
ZONE = 0x0BE
MOB = 0x01000000 | (ZONE << 12) | 0x020
POISON, FOOD, PROTECT = 3, 251, 40


def raw(expires_ms: int) -> int:
    return int((expires_ms / 1000 - EPOCH_S) * 60) % WRAP


def icons(*listed):
    """A status list: (status, expires_ms or None for no end) each."""
    fields = {"type": 9}
    for k in range(32):
        status, expires = listed[k] if k < len(listed) else (0xFF, 0)
        fields[f"data.icon[{k}]"] = status
        fields[f"data.timestamp[{k}]"] = 0x7FFFFFFF if expires is None else raw(expires) if expires else 0
    return 0x063, fields


def action(cat, arg, message, value, actor=MOB, target=PLAYER, proc=None):
    fields = {P + "actor_id": actor, P + "cmd_no": cat, P + "cmd_arg": arg, P + "target_count": 1,
              P + "targets[0].target_id": target, P + "targets[0].result_count": 1,
              P + "targets[0][0].message": message, P + "targets[0][0].value": value}  # fmt: skip
    if proc:
        fields[P + "targets[0][0].proc.message"], fields[P + "targets[0][0].proc.value"] = proc
    return 0x028, fields


BAT = (0x00E, {"UniqueNo": MOB, "ActIndex": 0x020, "Data.name": "LocusDireBat"})


def effects(*steps, times):
    return drive(Effects, *steps, times=times)["effects"]


def test_the_duration_is_what_the_status_list_gave_from_the_move_that_applied_it():
    # A bat's Jet Stream poisons the character; 0.6 s later its list holds Poison until 180 s after the move.
    hit = T0 + 1000
    steps = (BAT, action(11, 392, 242, POISON), icons((POISON, hit + 180_000)))
    (row,) = effects(*steps, times=[T0, hit, hit + 600])
    got = [row[k] for k in ("status_id", "duration_ms", "category", "action_id", "actor_name", "source_idx")]
    assert got == [POISON, 180_000, 11, 392, "LocusDireBat", 1]
    assert (row["renewed"], row["ended_ms"]) == (False, None)


def test_an_icon_listed_before_its_action_and_an_added_effect():
    # The list may come first; a melee hit's added effect names the status in its proc, never in its damage.
    hit = T0 + 1000
    steps = (BAT, icons((POISON, hit + 30_000)), action(1, 0, 1, POISON, proc=(160, POISON)))
    (row,) = effects(*steps, times=[T0, hit - 300, hit])
    assert (row["category"], row["message"], row["duration_ms"]) == (1, 160, 30_000)


def test_a_move_that_gives_its_effects_silently():
    # The move's result says only its damage (264); a party member's Cure for 145 HP, the status's number,
    # lands between it and the two icons the move gave.
    hit = T0 + 1000
    steps = (BAT, action(11, 4189, 264, 348), action(4, 1, 7, 145, actor=MEMBER),
             icons((145, hit + 45_000), (11, hit + 45_000)))  # fmt: skip
    rows = effects(*steps, times=[T0, hit, hit + 300, hit + 700])
    got = [(r["status_id"], r["action_id"], r["named"], r["actor_name"], r["duration_ms"]) for r in rows]
    assert got == [(145, 4189, False, "LocusDireBat", 45_000), (11, 4189, False, "LocusDireBat", 45_000)]
    # An icon that renews itself every few seconds takes no move that happened to hit just before.
    aura = (BAT, icons((404, hit + 5_000)), action(11, 4189, 264, 348), icons((404, hit + 10_000)))
    first, renewal = effects(*aura, times=[T0, hit, hit + 4_400, hit + 5_000])
    assert (renewal["renewed"], renewal.get("source_idx"), first.get("source_idx")) == (True, None, None)
    # A bard's March lands 400 ms after its icon, and a move hit 500 ms before it: the March names it. A
    # second March icon later, which no result names, is a buff the bard gave, not the next move's.
    march = lambda: action(4, 419, 266, 214, actor=MEMBER)  # noqa: E731
    steps = (BAT, action(11, 4189, 264, 348), icons((214, hit + 120_000)), march(),
             action(11, 4189, 264, 348), icons((214, hit + 120_000), (214, hit + 130_000)))  # fmt: skip
    sung, again = effects(*steps, times=[T0, hit - 500, hit, hit + 400, hit + 9_500, hit + 10_000])
    assert (sung["category"], sung["named"], again.get("source_idx")) == (4, True, None)
    # KO is the defeat, which no move gives as an effect, though one hit just before.
    (ko,) = effects(BAT, action(4, 0, 252, 0), icons((0, hit + 3_600_000)), times=[T0, hit, hit + 500])
    assert (ko["status_id"], ko.get("source_idx")) == (0, None)


def test_a_silent_move_lands_and_gives_no_buff():
    """Dendainsonne's Wild Horn, archived: a Regen icon 1 s after it, which no result names. Regen is a buff,
    which a mob's move never gives. A missed move (188) gives nothing, though a stun icon follows it."""
    hit = T0 + 1000
    (regen,) = effects(
        BAT, action(11, 628, 185, 300), icons((42, hit + 120_000)), times=[T0, hit, hit + 1000]
    )
    assert regen.get("source_idx") is None
    missed = action(11, 629, 188, 0)
    missed[1][P + "targets[0][0].miss"] = 1
    (stun,) = effects(BAT, missed, icons((10, hit + 7_000)), times=[T0, hit, hit + 500])
    assert stun.get("source_idx") is None


def test_a_capture_an_hour_behind_the_server():
    """pBwCYcKf4DQ8, a 2023 PacketViewer log stamped in local time: every icon ran out an hour after its
    expiry by the capture's clock. Its stun read 3,607 s; set back an hour, it lasted 7 s, as it did."""
    hit, ahead = T0 + 1000, 3_600_000
    steps = (BAT, action(11, 629, 185, 300), icons((10, hit + ahead + 7_000)), icons(),
             icons((POISON, hit + ahead + 30_000)), icons(),
             icons((PROTECT, hit + ahead + 60_000)), icons())  # fmt: skip
    times = [T0, hit, hit + 300, hit + 7_400, hit + 8_000, hit + 30_300, hit + 31_000, hit + 60_200]
    rows = effects(*steps, times=times)
    assert [(r["status_id"], r["duration_ms"]) for r in rows] == [(10, 7_000), (POISON, 30_000 - 8_000),
                                                                   (PROTECT, 60_000 - 31_000)]  # fmt: skip
    assert rows[0]["expires_ms"] == hit + 7_000
    # Two ended icons, an hour apart: too few to tell, so nothing is set back.
    steps = (icons((PROTECT, T0 + ahead)), icons(), icons((FOOD, T0 + 60_000)), icons())
    rows = effects(*steps, times=[T0, T0 + 1000, T0 + 2000, T0 + 60_000])
    assert rows[0]["expires_ms"] == T0 + ahead


def test_a_renewal_a_zone_in_and_the_end():
    # Protect cast, cast again 600 s later, a zone-in that lists it 4 s later than before, and it wears off.
    first, again = T0, T0 + 600_000
    cast = lambda: action(4, 43, 230, PROTECT, actor=MEMBER)  # noqa: E731
    steps = (
        cast(), icons((PROTECT, first + 1_800_000)),
        cast(), icons((PROTECT, again + 1_800_000)),
        (0x00A, {"ZoneNo": ZONE}), icons(), icons((PROTECT, again + 1_804_000)),
        icons(),
    )  # fmt: skip
    times = [first, first + 500, again, again + 500, again + 60_000, again + 60_100, again + 62_000,
             T0 + 2_404_000]  # fmt: skip
    a, b = effects(*steps, times=times)
    assert (a["renewed"], a["ended_ms"], a["duration_ms"]) == (False, again + 500, 1_800_000)
    assert (b["renewed"], b["ended_ms"], b["actor_id"]) == (True, T0 + 2_404_000, MEMBER)


def test_food_takes_the_item_eaten_and_an_unclaimed_icon_has_no_source():
    eat = action(5, 4422, 0, 0, actor=PLAYER)
    steps = (eat, icons((FOOD, T0 + 1_800_000)), icons((FOOD, T0 + 1_800_000), (143, None)))
    food, other = effects(*steps, times=[T0, T0 + 700, T0 + 900])
    keys = ("status_id", "category", "action_id", "source_idx", "expires_ms", "duration_ms")
    assert [food[k] for k in keys] == [FOOD, 5, 4422, 0, T0 + 1_800_000, 1_800_000]
    assert [other.get(k) for k in keys] == [143, None, None, None, None, None]


def test_the_expiry_wraps_every_two_years():
    now = T0 + 5_000
    assert expiry_ms(raw(now + 90_000), now) == now + 90_000
    later = (EPOCH_S + (WRAP * 3 + 7) // 60) * 1000  # just past a wrap: the raw value is small again
    assert expiry_ms(raw(later + 60_000), later) == later + 60_000


def test_the_characters_defeats():
    steps = (
        BAT,
        (0x029, {"UniqueNoCas": MOB, "UniqueNoTar": PLAYER, "MessageNum": 97}),
        (0x029, {"UniqueNoCas": PLAYER, "UniqueNoTar": PLAYER, "MessageNum": 20}),
        (0x029, {"UniqueNoCas": PLAYER, "UniqueNoTar": MOB, "MessageNum": 6}),  # the bat's defeat
        (0x029, {"UniqueNoCas": MOB, "UniqueNoTar": MEMBER, "MessageNum": 97}),
    )
    got = [(r["message"], r["killer_id"], r["killer_name"]) for r in drive(Defeats, *steps)["defeats"]]
    assert got == [(97, MOB, "LocusDireBat"), (20, None, None)]


def capture(con, cid="e"):
    put(con, "captures", [{"capture_id": cid, "client_version": "v", "release": "r", "retail": True,
                           "packets": 0, "character_id": PLAYER, "character": "Me"}])  # fmt: skip
    put(con, "party", [{"capture_id": cid, "idx": 0, "ts_ms": 0, "client_version": "v", "member_id": MEMBER,
                        "name": "Nours"}])  # fmt: skip
    name = {"release": "r", "log_id": 0}
    put(con, "names", [
        {**name, "kind": "status", "id": POISON, "name": "Poison"},
        {**name, "kind": "status", "id": FOOD, "name": "Food"},
        {**name, "kind": "mob_skill", "id": 392, "name": "Jet Stream"},
        {**name, "kind": "item", "id": 4422, "name": "Orange Juice"},
        {**name, "kind": "item", "id": 4112, "name": "Potion"},
    ])  # fmt: skip
