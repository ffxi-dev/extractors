"""The combat extractors on hand-built packets, one per spec scenario in scholar-combat."""

import struct

from conftest import MOB, PLAYER, drive, raw

from ffxi_extractors.extractors import Actions, Character, Delay, Fights, Hp, Immunity
from ffxi_extractors.extractors.combat import P
from ffxi_extractors.extractors.hp import _Mob

MOB2 = MOB + 1
OTHER = 0x0001_0002


def r(message, value=0, sub_kind=0, bit=0, proc=None, react=None, miss=0):
    return {
        "message": message,
        "value": value,
        "sub_kind": sub_kind,
        "bit": bit,
        "proc": proc,
        "react": react,
        "miss": miss,
    }


def act(actor, cat, arg, targets):
    """A 0x028 packet: the bitstream the decoder reads, LSB first from byte 5."""
    acc, n = 0, 0

    def w(v, bits):
        nonlocal acc, n
        acc |= (v & ((1 << bits) - 1)) << n
        n += bits

    w(actor, 32), w(len(targets), 6), w(0, 4), w(cat, 4), w(arg, 32), w(0, 32)
    for tid, results in targets:
        w(tid, 32), w(len(results), 4)
        for x in results:
            for v, bits in ((x["miss"], 3), (0, 2), (x["sub_kind"], 12), (0, 5), (0, 5), (x["value"], 17),
                            (x["message"], 10), (x["bit"], 31)):  # fmt: skip
                w(v, bits)
            for extra, vbits in ((x["proc"], 17), (x["react"], 14)):
                w(1 if extra else 0, 1)
                if extra:  # (value, message)
                    w(0, 6), w(0, 4), w(extra[0], vbits), w(extra[1], 10)
    body = acc.to_bytes((n + 7) // 8, "little")
    size = (5 + len(body) + 3) // 4 * 4
    data = bytearray(size)
    data[0], data[1], data[4] = 0x28, (size // 4) << 1, len(body)
    data[5 : 5 + len(body)] = body
    return 0x028, bytes(data)


def message(caster, target, num, data1=0, data2=0):
    """A 0x029 battle message."""
    data = bytearray(28)
    data[0], data[1] = 0x29, (28 // 4) << 1
    struct.pack_into("<IIIIHHH", data, 4, caster, target, data1, data2, 1, target & 0xFFF, num)
    return 0x029, bytes(data)


def vitals(tp, who=PLAYER):
    """A 0x0DF party update: a member's HP, MP, and TP."""
    data = bytearray(40)
    data[0], data[1] = 0xDF, (40 // 4) << 1
    struct.pack_into("<IIII", data, 4, who, 1000, 100, tp)
    return 0x0DF, bytes(data)


def status(who=PLAYER):
    """A 0x037: the character's own status, which names its id."""
    data = bytearray(48)
    data[0], data[1] = 0x37, (48 // 4) << 1
    struct.pack_into("<I", data, 36, who)
    return 0x037, bytes(data)


def test_a_tp_move_on_two_party_members():
    rows = raw(Actions, (1000, act(MOB, 11, 2000, [(PLAYER, [r(185, 300)]), (OTHER, [r(185, 250)])])))
    (a,) = rows["actions"]
    assert (a["actor_id"], a["actor_is_mob"], a["category"], a["action_id"], a["targets"]) == (
        MOB,
        True,
        11,
        2000,
        2,
    )
    assert [(x["target_id"], x["value"], x["message"]) for x in rows["action_results"]] == [
        (PLAYER, 300, 185),
        (OTHER, 250, 185),
    ]


def test_a_start_carries_its_id_and_the_finish_its_ready_time():
    rows = raw(
        Actions,
        (1000, act(MOB, 7, 0, [(PLAYER, [r(43, 2000)])])),
        (3500, act(MOB, 11, 2000, [(PLAYER, [r(185, 10)])])),
    )
    start, finish = rows["actions"]
    assert (start["action_id"], start["ready_ms"], finish["ready_ms"]) == (2000, None, 2500)


def test_a_finish_pairs_only_with_its_own_start():
    """An interrupt (cmd_arg's low half 28787) stops its start and carries its id and time; a finish after it,
    one after another move's start, and one 40 s after its start have no ready time. A spell pairs with its
    own start."""
    stop = 0x6574_7073
    rows = raw(
        Actions,
        (1000, act(MOB, 7, 0, [(PLAYER, [r(43, 2000)])])),
        (1800, act(MOB, 7, stop, [(PLAYER, [r(0, 0)])])),
        (9000, act(MOB, 11, 2000, [(PLAYER, [r(185, 10)])])),
        (10000, act(MOB, 7, 0, [(PLAYER, [r(43, 2001)])])),
        (11000, act(MOB, 11, 2000, [(PLAYER, [r(185, 10)])])),
        (20000, act(MOB, 7, 0, [(PLAYER, [r(43, 2000)])])),
        (60000, act(MOB, 11, 2000, [(PLAYER, [r(185, 10)])])),
        (61000, act(MOB, 8, 0, [(PLAYER, [r(327, 144)])])),
        (63500, act(MOB, 4, 144, [(PLAYER, [r(2, 50)])])),
    )["actions"]
    assert [(x["category"], x["action_id"], x["ready_ms"]) for x in rows] == [
        (7, 2000, None),
        (7, 2000, 800),
        (11, 2000, None),
        (7, 2001, None),
        (11, 2000, None),
        (7, 2000, None),
        (11, 2000, None),
        (8, 144, None),
        (4, 144, 2500),
    ]


def test_a_mobs_ten_attacks_give_nine_intervals():
    hits = [act(MOB, 1, 0, [(PLAYER, [r(1, 20)] + [r(15)] * (i % 2))]) for i in range(10)]
    rows = raw(Delay, *[(1000 + 3000 * i, p) for i, p in enumerate(hits)])["attack_rounds"]
    assert [x["interval_ms"] for x in rows] == [None] + [3000] * 9
    assert [x["swings"] for x in rows][:2] == [1, 2] and all(x["hits"] == 1 for x in rows)


def test_a_tp_move_pauses_the_delay():
    rows = raw(
        Delay,
        (0, act(MOB, 1, 0, [(PLAYER, [r(1, 5)])])),
        (1000, act(MOB, 11, 2000, [(PLAYER, [r(185, 5)])])),
        (4000, act(MOB, 1, 0, [(PLAYER, [r(1, 5)])])),
        (7000, act(MOB, 1, 0, [(PLAYER, [r(1, 5)])])),
    )["attack_rounds"]
    assert [x["interval_ms"] for x in rows] == [None, None, 3000]


def test_an_immunity_and_resists():
    rows = raw(
        Immunity,
        (0, act(PLAYER, 4, 253, [(MOB, [r(655)])])),
        (10, act(PLAYER, 4, 253, [(MOB2, [r(85, bit=2)])])),
        (20, act(PLAYER, 4, 253, [(MOB2, [r(85)])])),
        (30, act(PLAYER, 4, 1, [(OTHER, [r(7, 50)])])),  # a cure on a party member is not a mob's
    )["spell_results"]
    assert [(x["target_id"], x["spell_id"], x["outcome"]) for x in rows] == [
        (MOB, 253, "immune"),
        (MOB2, 253, "trait_resist"),
        (MOB2, 253, "resist"),
    ]


def test_a_defeated_mob_took_melee_a_weapon_skill_and_a_skillchain():
    rows = raw(
        Hp,
        (0, act(PLAYER, 1, 0, [(MOB, [r(1, 100)])])),
        (1000, act(PLAYER, 3, 32, [(MOB, [r(185, 500, proc=(300, 288))])])),
        (2000, message(PLAYER, MOB, 6)),
    )["mob_hp"]
    (m,) = rows
    assert (m["mob_id"], m["damage"], m["hits"], m["hp_min"], m["hp_max"]) == (MOB, 900, 3, 101, 900)


def test_a_despawn_ends_the_damage_count():
    gone = bytearray(48)
    gone[0], gone[1] = 0x0E, (48 // 4) << 1
    struct.pack_into("<IHB", gone, 4, MOB, MOB & 0xFFF, 0x20)  # SendFlg.Despawn
    rows = raw(
        Hp,
        (0, act(PLAYER, 1, 0, [(MOB, [r(1, 100)])])),
        (1000, (0x00E, bytes(gone))),
        (2000, act(PLAYER, 1, 0, [(MOB, [r(1, 200)])])),
        (3000, message(PLAYER, MOB, 6)),
    )["mob_hp"]
    assert [(m["damage"], m["hits"]) for m in rows] == [(200, 1)]


def hpp(who, pct):
    """A 0x00E entity update with the General flag: who's HP%."""
    data = bytearray(48)
    data[0], data[1] = 0x0E, (48 // 4) << 1
    struct.pack_into("<IHB", data, 4, who, who & 0xFFF, 0x04)
    data[0x1E] = pct
    return 0x00E, bytes(data)


def test_regen_restarts_the_hp_window_and_gives_its_rate():
    # 1000 HP: 100 damage takes the bar to 90, regen brings it back 1% a tick, then 300 damage takes 30%.
    rows = raw(
        Hp,
        (0, hpp(MOB, 100)),
        (1000, act(PLAYER, 1, 0, [(MOB, [r(1, 100)])])),
        (1100, hpp(MOB, 90)),
        (4000, hpp(MOB, 91)),
        (7000, hpp(MOB, 92)),
        (10000, hpp(MOB, 93)),
        (11000, act(PLAYER, 1, 0, [(MOB, [r(1, 300)])])),
        (11100, hpp(MOB, 63)),
        (12000, act(PLAYER, 1, 0, [(MOB, [r(1, 700)])])),
        (13000, message(PLAYER, MOB, 6)),
    )["mob_hp"]
    (m,) = rows
    assert (m["regen"], m["regen_rate"], m["healing"]) == (3, 1.0, 0)
    # Counting the 100 damage before the regen would put the least HP at 1,082.
    assert m["hp_min"] <= 1000 <= m["hp_max"], "the damage before the regen no longer counts"


def test_slow_regen_gives_its_rate_and_a_hit_between_rises_breaks_the_run():
    # Fafnir: a point every 90 s with nobody hitting it. The hit at 200 s falls between two rises, so the
    # 90 s after it don't count.
    rows = raw(
        Hp,
        (0, hpp(MOB, 100)),
        (1000, act(PLAYER, 1, 0, [(MOB, [r(1, 100)])])),
        (1100, hpp(MOB, 90)),
        (20000, hpp(MOB, 91)),
        (110000, hpp(MOB, 92)),
        (200000, hpp(MOB, 93)),
        (250000, act(PLAYER, 1, 0, [(MOB, [r(1, 1)])])),
        (290000, hpp(MOB, 94)),
        (300000, act(PLAYER, 1, 0, [(MOB, [r(1, 940)])])),
        (301000, message(PLAYER, MOB, 6)),
    )["mob_hp"]
    assert (rows[0]["regen"], rows[0]["regen_rate"]) == (4, round(2 * 3000 / 180000, 4))


def test_under_regen_the_hp_most_windows_allow_wins_over_the_first():
    # One window thrown off by regen the bar didn't show yet comes first; the rest agree on 980-1,020.
    m = _Mob(100, 100)
    m.regen = 1
    m.windows = [(1300, 1400), (900, 1100), (950, 1050), (980, 1020), (970, 1200)]
    assert m.range() == (980, 1020)


def test_a_rise_after_a_heal_is_not_regen():
    rows = raw(
        Hp,
        (0, hpp(MOB, 100)),
        (1000, act(PLAYER, 1, 0, [(MOB, [r(1, 100)])])),
        (1100, hpp(MOB, 90)),
        (2000, act(MOB, 4, 1, [(MOB, [r(7, 50)])])),
        (2100, hpp(MOB, 95)),
        (3000, act(PLAYER, 1, 0, [(MOB, [r(1, 950)])])),
        (4000, message(PLAYER, MOB, 6)),
    )["mob_hp"]
    assert (rows[0]["regen"], rows[0]["regen_rate"], rows[0]["healing"]) == (0, None, 50)


def test_a_kill_whose_hp_fell_with_no_damage_seen_gives_no_hp():
    """The owner's Errand Imp: level 80 read 1,815 HP, under level 79's 3,051, from kills a Helix
    finished; its ticks send no action, so the damage seen fell short of the HP. An HP% fall the action
    after explains is no such fall."""
    dot = raw(
        Hp,
        (0, hpp(MOB, 100)),
        (1000, act(PLAYER, 1, 0, [(MOB, [r(1, 100)])])),
        (1100, hpp(MOB, 90)),
        (5000, hpp(MOB, 80)),  # a tick: no action before or soon after
        (9000, act(PLAYER, 1, 0, [(MOB, [r(1, 900)])])),
        (9100, message(PLAYER, MOB, 6)),
    )["mob_hp"]
    assert dot == []
    late = raw(
        Hp,
        (0, hpp(MOB, 100)),
        (500, act(PLAYER, 1, 0, [(MOB, [r(1, 100)])])),
        (600, hpp(MOB, 90)),
        (2000, hpp(MOB, 80)),  # the bar before the action that moved it
        (2400, act(PLAYER, 1, 0, [(MOB, [r(1, 100)])])),
        (3000, act(PLAYER, 1, 0, [(MOB, [r(1, 800)])])),
        (3100, message(PLAYER, MOB, 6)),
    )["mob_hp"]
    assert [x["damage"] for x in late] == [1000]


def test_spikes_damage_the_attacker():
    rows = raw(
        Hp,
        (0, act(MOB, 1, 0, [(PLAYER, [r(1, 30, react=(40, 44))])])),
        (1000, act(PLAYER, 1, 0, [(MOB, [r(1, 60)])])),
        (2000, message(PLAYER, MOB, 6)),
    )["mob_hp"]
    assert rows[0]["damage"] == 100


def test_a_countered_swing_is_no_hit_on_the_mob():
    """A counter did no damage to the mob, but counted as a hit: the kill's range came out (501, 500)."""
    (m,) = raw(
        Hp,
        (0, act(PLAYER, 1, 0, [(MOB, [r(1, 500)])])),
        (1000, act(PLAYER, 1, 0, [(MOB, [r(33, react=(50, 33))])])),
        (2000, message(PLAYER, MOB, 6)),
    )["mob_hp"]
    assert (m["hits"], m["hp_min"], m["hp_max"]) == (1, 1, 500)


def test_a_trust_that_falls_is_no_mob():
    trust = MOB | 0x700
    rows = raw(
        Hp,
        (0, act(MOB, 1, 0, [(trust, [r(1, 300)])])),
        (1000, message(MOB, trust, 6)),
    )["mob_hp"]
    assert rows == []


def test_regen_with_no_window_left_standing_falls_back_on_the_damage():
    m = _Mob(100, 100)
    m.regen, m.windows = 1, [(10, 5)]  # healed, then hit by a tick: every window inverted
    m.hit(300, False, 0)
    assert m.range() == (1, 300)


def test_hp_tracks_no_player_and_ends_on_the_last_hit_and_its_procs():
    """A mob's hits on the party made a tracker per player, kept until the zone changed; each round summed
    the mob's whole hit list again (Codex's review, 9)."""
    hp = Hp()
    rows = raw(
        lambda: hp,
        (0, act(MOB, 1, 0, [(PLAYER, [r(1, 30, react=(40, 44))])])),
        (500, act(OTHER, 4, 1, [(PLAYER, [r(7, 20)])])),
        (1000, act(PLAYER, 1, 0, [(MOB, [r(1, 60)]), (MOB, [r(1, 5, proc=(7, 163))])])),
        (2000, message(PLAYER, MOB, 6)),
    )["mob_hp"]
    assert hp.mobs == {}, "the player hit and healed has no tracker"
    (m,) = rows
    assert (m["damage"], m["hits"], m["hp_min"], m["hp_max"]) == (112, 4, 101, 112)


def test_fights_end_at_defeat_and_a_defeat_alone_is_a_fight():
    rows = raw(
        Fights,
        (0, act(PLAYER, 1, 0, [(MOB, [r(1, 10)])])),
        (3000, act(MOB, 1, 0, [(PLAYER, [r(1, 10)])])),
        (6000, message(PLAYER, MOB, 6)),
        (7000, message(OTHER, MOB2, 6)),
        (8000, act(PLAYER, 1, 0, [(MOB, [r(1, 10)])])),  # the same id again: its next life
    )["fights"]
    assert [
        (x["mob_id"], x["idx"], x["end_idx"], x["outcome"], x["actions"], x["actions_by"]) for x in rows
    ] == [
        (MOB, 0, 2, "defeated", 2, 1),
        (MOB2, 3, 3, "defeated", 0, 0),
        (MOB, 4, 4, "open", 1, 0),
    ]


def test_a_resent_defeat_is_one_fight():
    defeat = message(PLAYER, MOB, 6)
    rows = raw(Fights, (0, act(PLAYER, 1, 0, [(MOB, [r(1, 10)])])), (3000, defeat), (3000, defeat))["fights"]
    assert [(x["mob_id"], x["outcome"], x["actions"]) for x in rows] == [(MOB, "defeated", 1)]


def test_a_mob_buffing_itself_or_another_mob_is_no_fight():
    rows = raw(
        Fights,
        (0, act(MOB, 4, 250, [(MOB, [r(230)])])),
        (5000, act(MOB, 4, 108, [(MOB2, [r(230)])])),
    )["fights"]
    assert rows == []


def test_a_fight_left_alone_closes_and_the_next_action_opens_another():
    later = 3000 + 180_001
    rows = raw(
        Fights,
        (0, act(PLAYER, 1, 0, [(MOB, [r(1, 10)])])),
        (3000, act(MOB, 1, 0, [(PLAYER, [r(1, 10)])])),
        (100_000, act(MOB, 4, 250, [(MOB, [r(230)])])),  # its own spikes: counted, but no extension
        (later, act(PLAYER, 1, 0, [(MOB, [r(1, 10)])])),
        (later + 180_001, act(MOB2, 4, 250, [(MOB2, [r(230)])])),  # the capture goes on, then ends
    )["fights"]
    assert [(x["idx"], x["end_idx"], x["end_ms"], x["outcome"], x["actions"]) for x in rows] == [
        (0, 1, 3000, "disengaged", 3),
        (3, 3, later, "disengaged", 1),
    ]


def test_a_resend_counts_once():
    p = act(MOB, 1, 0, [(PLAYER, [r(1, 10)])])
    rows = raw(Actions, (0, p), (200, p))
    assert [x["resend"] for x in rows["actions"]] == [False, True]
    assert len(raw(Delay, (0, p), (200, p))["attack_rounds"]) == 1


def rounds(*packets, step=3000):
    return raw(Delay, *[(step * i, p) for i, p in enumerate(packets)])["attack_rounds"]


OUTCOME_COLUMNS = ("crits", "misses", "parried", "absorbed", "anticipated", "countered", "dodged", "blocked",
                   "guarded", "other")  # fmt: skip


def outcomes(row):
    return {k: row[k] for k in OUTCOME_COLUMNS if row[k]}


def test_each_swing_counts_under_one_outcome():
    swings = [
        r(1, 20),  # a plain hit: no outcome column
        r(67, 40),
        r(15),
        r(70),
        r(31),
        r(30),
        r(32),
        r(1, 15, miss=4),
        r(1, 15, miss=2),
        r(1, 20, react=(30, 33)),
        r(1, 0, react=(0, 14)),  # a counter a shadow absorbed, not an evasion
        r(67, 40, miss=4),  # a blocked critical hit is blocked
        r(999),
    ]
    rows = rounds(*[act(MOB, 1, 0, [(PLAYER, [s])]) for s in swings])
    assert [outcomes(x) for x in rows] == [
        {},
        {"crits": 1},
        {"misses": 1},
        {"parried": 1},
        {"absorbed": 1},
        {"anticipated": 1},
        {"dodged": 1},
        {"blocked": 1},
        {"guarded": 1},
        {"countered": 1},
        {"countered": 1},
        {"blocked": 1},
        {"other": 1},
    ]
    assert [x["hits"] for x in rows] == [1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0]
    assert all(x["at_character"] and x["targets"] == 1 and not x["cut_short"] for x in rows)


def test_a_double_attack_into_shadows():
    (x,) = rounds(act(MOB, 1, 0, [(PLAYER, [r(31), r(1, 20)])]))
    assert (x["swings"], x["main_hand"], x["hits"], outcomes(x)) == (2, 2, 1, {"absorbed": 1})


def test_hands_kicks_and_targets():
    (x,) = rounds(act(MOB, 1, 0, [(OTHER, [r(1, 9), r(1, 9, sub_kind=1), r(15, sub_kind=2)]), (PLAYER, [])]))
    assert (x["main_hand"], x["off_hand"], x["kicks"], x["targets"], x["at_character"]) == (1, 1, 1, 2, False)


def test_a_round_that_kills_is_cut_short():
    rows = raw(
        Delay,
        (0, act(MOB, 1, 0, [(PLAYER, [r(1, 20)])])),
        (500, message(MOB, PLAYER, 97)),  # the character falls within the second
        (3000, act(MOB2, 1, 0, [(OTHER, [r(1, 20)])])),
        (6000, message(MOB2, OTHER, 97)),  # three seconds on: another cause
    )["attack_rounds"]
    assert [x["cut_short"] for x in rows] == [True, False]


def test_a_respawn_starts_a_new_interval():
    hit = act(MOB, 1, 0, [(PLAYER, [r(1, 20)])])
    rows = raw(Delay, (0, hit), (2000, message(PLAYER, MOB, 6)), (302_000, hit), (305_000, hit))
    assert [x["interval_ms"] for x in rows["attack_rounds"]] == [None, None, 3000]


def test_a_mob_out_of_view_starts_a_new_interval():
    t = P + "targets[0]"
    hit = (0x028, {P + "actor_id": MOB, P + "cmd_no": 1, P + "target_count": 1, t + ".target_id": PLAYER,
                   t + ".result_count": 1, t + "[0].message": 1})  # fmt: skip
    gone = (0x00E, {"UniqueNo": MOB, "ActIndex": MOB & 0xFFF, "SendFlg.Despawn": 1})
    rows = drive(Delay, hit, hit, gone, hit, times=[0, 3000, 4000, 90_000])["attack_rounds"]
    assert [x["interval_ms"] for x in rows] == [None, 3000, None]


def test_a_hit_worth_21_tp_is_a_240_delay():
    (x,) = raw(
        Delay,
        (0, vitals(100)),
        (1000, act(MOB, 1, 0, [(PLAYER, [r(1, 20)])])),
        (1100, vitals(500, who=OTHER)),  # a party member's update does not count
        (1200, vitals(121)),
    )["attack_rounds"]
    assert x["tp_gain"] == 21 and x["tp_gain"] * 240 / 21 == 240


def test_tp_gains_that_cannot_be_told_apart():
    rows = raw(
        Delay,
        (0, vitals(100)),
        (1000, act(MOB, 1, 0, [(PLAYER, [r(1, 20)])])),
        (2000, act(MOB2, 1, 0, [(PLAYER, [r(1, 20)])])),  # a second hit before the update
        (2100, vitals(142)),
        (3000, act(MOB, 1, 0, [(PLAYER, [r(1, 20), r(1, 20)])])),  # a double attack
        (3100, vitals(184)),
        (4000, act(MOB, 1, 0, [(PLAYER, [r(15)])])),  # a miss gives no TP
        (4100, vitals(184)),
        (5000, act(PLAYER, 1, 0, [(MOB, [r(1, 30)])])),  # the character's own swing first
        (6000, act(MOB, 1, 0, [(PLAYER, [r(1, 20)])])),
        (6100, vitals(260)),
        (9000, act(MOB, 1, 0, [(PLAYER, [r(1, 20)])])),
        (9100, vitals(300)),  # 40 more: counted, the query keeps 9 to 53
    )["attack_rounds"]
    assert [x.get("tp_gain") for x in rows if x["actor_is_mob"]] == [None, None, None, None, None, 40]


def test_a_checkparam():
    rows = raw(
        Character,
        (0, message(PLAYER, PLAYER, 712, 1050, 1200)),
        (0, message(PLAYER, PLAYER, 715, 980, 1100)),
        (0, message(PLAYER, OTHER, 715, 1, 1)),  # about someone else
    )["character_params"]
    keys = ("kind", "accuracy", "attack", "evasion", "defense")
    assert [tuple(x.get(k) for k in keys) for x in rows] == [
        ("main", 1050, 1200, None, None),
        ("defense", None, None, 980, 1100),
    ]


def tp_move(*targets):
    """A mob TP move on targets, as decoded fields."""
    d = {P + "actor_id": MOB, P + "cmd_no": 11, P + "cmd_arg": 2000, P + "target_count": len(targets)}
    for i, t in enumerate(targets):
        tp = f"{P}targets[{i}]"
        d |= {tp + ".target_id": t, tp + ".result_count": 1, tp + "[0].message": 264, tp + "[0].scale": 13}
    return 0x028, d


def at(op, uid, x, y, z=0.0):  # an NPC, mob, or trust (0x00E) or player (0x00D) update with its position
    return op, {"UniqueNo": uid, "ActIndex": uid & 0xFFF, "SendFlg.Position": 1, "x": x, "y": y, "z": z}


def me(x, y, z=0.0):  # the character's own position, c2s 0x015
    return 0x015, {"x": x, "y": y, "z": z}


def measured(rows):
    return [(a["max_range"], a["max_spread"] and round(a["max_spread"], 2)) for a in rows["actions"]]


def test_a_tp_move_reach_and_spread():
    steps = [at(0x00E, MOB, 0.0, 0.0), at(0x00D, OTHER, 3.0, 4.0), me(0.0, -6.0), tp_move(PLAYER, OTHER),
             tp_move(MOB), tp_move(OTHER, 0x0001_0009)]  # fmt: skip
    rows = drive(Actions, *steps, directions=[0, 0, 1, 0, 0, 0])
    # 5 and 6 yalms from the mob, 10.44 apart; a move on itself has no target to measure; one target never
    # placed leaves both unknown.
    assert measured(rows) == [(6.0, 10.44), (None, None), (None, None)]
    assert [x["scale"] >> 2 for x in rows["action_results"][:2]] == [3, 3]  # knockback 3


def test_a_tp_move_in_a_captain_log():
    # No zone-in names the character: 0x037 does, so its own position counts.
    steps = [at(0x00E, MOB, 0.0, 0.0), me(0.0, -6.0), (0x037, {"UniqueNo": PLAYER}), tp_move(PLAYER)]
    rows = drive(Actions, *steps, directions=[0, 1, 0, 0], me=0)
    assert measured(rows) == [(6.0, None)]


def test_who_stood_near_a_tp_move():
    # The mob at the origin faces +x (heading 0), then -y (64), then its heading goes stale. The character 5
    # ahead and a stranger 4 to one side are hit; a party member 8 behind and another mob 3 to the other side
    # are not. A player at 0 HP and one 40 away are left out.
    stranger, fallen, far = 0x0001_0003, 0x0001_0004, 0x0001_0005

    def mob(heading):
        return 0x00E, at(0x00E, MOB, 0.0, 0.0)[1] | {"dir": heading, "SendFlg.General": 1, "Flags2.g": 32}

    steps = [mob(0), me(5.0, 0.0), at(0x00D, stranger, 0.0, 4.0), at(0x00D, OTHER, -8.0, 0.0),
             at(0x00E, MOB2, 0.0, -3.0), at(0x00D, fallen, 2.0, 2.0),
             (0x00D, {"UniqueNo": fallen, "SendFlg.General": 1, "Hpp": 0}), at(0x00D, far, 40.0, 0.0),
             tp_move(PLAYER, stranger), mob(64), tp_move(PLAYER, stranger),
             tp_move(PLAYER, stranger)]  # fmt: skip
    times = [0, 100, 200, 300, 400, 500, 600, 700, 1000, 1100, 1200, 5000]
    rows = drive(Actions, *steps, times=times, directions=[0, 1] + [0] * 10)
    assert [(a["actor_dir"], a["actor_size"]) for a in rows["actions"]] == [(0, 3.2), (64, 3.2), (None, 3.2)]

    def near(r):
        b, t = r["bearing"], r["from_target"]
        return r["entity_id"], r["hit"], r["party"], round(r["distance"], 2), b and round(b), round(t, 2)

    got = [[near(r) for r in rows["tp_nearby"] if r["idx"] == i] for i in (8, 10, 11)]
    assert got[0] == [
        (stranger, True, False, 4.0, -90, 6.4),
        (OTHER, False, True, 8.0, -180, 13.0),
        (MOB2, False, False, 3.0, 90, 5.83),
        (PLAYER, True, True, 5.0, 0, 0.0),
    ]
    assert [x[4] for x in got[1]] == [-180, 90, 0, -90]  # facing -y
    assert [x[4] for x in got[2]] == [None] * 4  # 3.9 s after the mob's last heading
    assert [r["age_ms"] for r in rows["tp_nearby"][:4]] == [800, 700, 600, 900]


def test_rounds_at_the_character_in_a_captain_log():
    # No zone-in names the character: 0x037 does.
    hit = act(MOB, 1, 0, [(PLAYER, [r(1, 5)])])
    rows = raw(Delay, (0, status()), (1000, hit), (4000, hit), me=0)["attack_rounds"]
    assert [x["at_character"] for x in rows] == [True, True]
