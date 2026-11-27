"""A mob page's job signs (bestiary_jobs): each sign with the jobs that give it at the mob's level, and its
packets in Lens."""

from fill import ask, put

ZONE = 0x0BE
MOB = 0x01000000 | (ZONE << 12) | 0x030
FIRE, SLEEP, STUN = 144, 253, 252
MIGHTY_STRIKES, HUNDRED_FISTS = 688, 690
LENS = "https://lens.sruon.dev/c/"


def use(idx, skill):
    return {"idx": idx, "id": skill, "targets": 1, "reach": None, "spread": None, "size": None, "hit": None,
            "crit": None, "kb": 0, "ready": None, "near": [], "rules_out": [0, 0, 0, 0], "shadows": None,
            "shadow_exact": None, "through": None}  # fmt: skip


def taken(idx, spell, outcome):
    return {"spell": spell, "outcome": outcome, "immunobreak": False, "caster": 1, "idx": idx, "ms": 0}


def rounds(n, main=1, off=0, kicks=0):
    return [{"swings": main + off + kicks, "main_hand": main, "off_hand": off, "kicks": kicks}] * n


def test_a_mobs_signs_name_their_jobs_and_packets_once_per_fight(con):
    capture = {"client_version": "v", "release": "r", "retail": True, "packets": 0}
    put(con, "captures", [{**capture, "capture_id": c} for c in "abc"])
    put(con, "capture_trust", [{"capture_id": "c", "trust": "flagged", "at": 0}])
    job = {"release": "r", "kind": "spell_job", "id": FIRE}
    put(con, "names", [{**job, "log_id": n, "name": j, "log": str(lv)}
                       for n, j, lv in ((4, "BLM", 13), (5, "RDM", 19), (8, "DRK", 23))])  # fmt: skip
    # Double Attack: 5 of the 40 rounds whose first swing hit swung twice; 2 of 20 after a miss is no
    # Zanshin. Triple Attack: 3 of 60 rounds. A Sleep and a Stun met "Resist!"; it used Mighty Strikes and
    # Hundred Fists.
    champion = {
        "zone_id": ZONE, "mob_id": MOB, "name": "Orcish Champion", "mob_name": "Orcish Champion",
        "model_id": 7, "level": 60, "idx": 1, "end_idx": 1000, "fight_key": 1,
        "first_swings": [{"main_hand": 2, "first_missed": 0}] * 5 + [{"main_hand": 1, "first_missed": 0}] * 35
        + [{"main_hand": 2, "first_missed": 1}] * 2 + [{"main_hand": 1, "first_missed": 1}] * 18,
        "rounds": rounds(3, main=3) + rounds(7, main=2) + rounds(50), "spells": [FIRE],
        "taken": [taken(500, SLEEP, "trait_resist"), taken(502, SLEEP, "landed"),
                  taken(501, STUN, "trait_resist")],
        "tp": [use(600, MIGHTY_STRIKES), use(601, HUNDRED_FISTS)],
    }  # fmt: skip
    brawler = {"zone_id": ZONE, "mob_id": MOB + 1, "name": "Orcish Brawler", "mob_name": "Orcish Brawler",
               "model_id": 8, "level": 20, "idx": 1, "end_idx": 1000, "fight_key": 2,
               "rounds": rounds(20, off=1)}  # fmt: skip
    put(con, "bestiary_fights", [
        {**champion, "capture_id": "a"},
        {**champion, "capture_id": "b"},  # a party member's copy: counts once
        {**champion, "capture_id": "c", "fight_key": 3},  # Flagged
        {**brawler, "capture_id": "a"},
    ])  # fmt: skip
    swing = {"capture_id": "a", "client_version": "v", "actor_id": MOB, "actor_is_mob": True, "targets": 1,
             "cut_short": False}  # fmt: skip
    put(con, "attack_rounds", [{**swing, "idx": i, "ts_ms": i, "main_hand": main, "off_hand": 0, "kicks": 0}
                               for i, main in ((10, 2), (11, 3), (12, 2))])  # fmt: skip
    # Of 200 swings at it, it guarded 3: Guard, a Monk's or Puppetmaster's.
    at = {"capture_id": "a", "client_version": "v", "actor_id": 1, "actor_is_mob": False, "target_id": MOB}
    put(con, "attack_rounds", [{**at, "idx": 20, "ts_ms": 20, "swings": 200, "guarded": 3, "countered": 0}])
    first = {"capture_id": "a", "client_version": "v", "category": 1, "target_index": 0, "result_index": 0}
    put(con, "action_results", [{**first, "idx": 10, "ts_ms": 10, "miss": 0},
                                {**first, "idx": 12, "ts_ms": 12, "miss": 1}])  # fmt: skip
    put(con, "actions", [{"capture_id": "a", "idx": 13, "ts_ms": 13, "client_version": "v", "actor_id": MOB,
                          "category": 4, "action_id": FIRE, "resend": False}])  # fmt: skip

    got = [(r["sign"], r["id"], r["status"], r["jobs"], r["n"], r["of"], r["proofs"])
           for r in ask(con, "bestiary_jobs", zone=ZONE, name="Orcish Champion")]  # fmt: skip
    assert got == [
        ("double", 0, "", ["WAR"], 5, 40, [LENS + "a#packet=10"]),
        ("guard", 0, "", ["MNK", "PUP"], 3, 200, [LENS + "a#packet=20"]),
        ("resist", 0, "sleep", ["PLD"], 1, 2, [LENS + "a#packet=500"]),
        ("resist", 0, "stun", [], 1, 1, [LENS + "a#packet=501"]),  # no job has Resist Stun
        ("spell", FIRE, "", ["BLM", "DRK", "RDM"], 1, 1, [LENS + "a#packet=13"]),
        ("triple", 0, "", ["THF"], 3, 60, [LENS + "a#packet=11"]),
        ("two_hour", MIGHTY_STRIKES, "", ["WAR"], 1, 1, [LENS + "a#packet=600"]),
        ("two_hour", HUNDRED_FISTS, "", ["MNK"], 1, 1, [LENS + "a#packet=601"]),
    ]
    # At level 20, Dual Wield is Ninja's and Dancer's, not yet Thief's (83).
    (hands,) = ask(con, "bestiary_jobs", zone=ZONE, name="Orcish Brawler")
    assert (hands["sign"], hands["jobs"], hands["n"]) == ("two_hands", ["DNC", "MNK", "NIN", "PUP"], 20)


def test_a_mob_that_shoots_and_holds_a_wyvern_reads_as_a_shooter_and_a_dragoon(con):
    """Ranged attacks name RNG, COR, NIN, and THF; the entity after a mob, named as a mob's wyvern, is its
    pet, a Dragoon's. A mob named as a pet has no pet of its own."""
    capture = {"client_version": "v", "release": "r", "retail": True, "packets": 0}
    put(con, "captures", [{**capture, "capture_id": "a"}])
    fight = {"capture_id": "a", "zone_id": ZONE, "model_id": 9, "level": 60, "idx": 1, "end_idx": 1000}
    put(con, "bestiary_fights", [
        {**fight, "mob_id": MOB, "name": "Hydra Dragoon", "mob_name": "Hydra Dragoon", "fight_key": 4},
        {**fight, "mob_id": MOB + 1, "name": "Hydra's Wyvern", "mob_name": "Hydra's Wyvern", "fight_key": 5},
    ])  # fmt: skip
    put(con, "actions", [{"capture_id": "a", "idx": i, "ts_ms": i, "client_version": "v", "actor_id": MOB,
                          "category": 2, "action_id": 0, "resend": False} for i in (30, 31, 32)])  # fmt: skip
    seen = {"capture_id": "a", "client_version": "v", "ts_ms": 0, "entity_name": "Hydra's Wyvern"}
    put(con, "named_entities", [{**seen, "idx": 40, "entity_id": MOB + 1},
                                {**seen, "idx": 41, "entity_id": MOB + 2}])  # fmt: skip

    got = [(r["sign"], r["status"], r["jobs"], r["n"], r["proofs"][:1])
           for r in ask(con, "bestiary_jobs", zone=ZONE, name="Hydra Dragoon")]  # fmt: skip
    assert got == [
        ("pet", "wyvern", ["DRG"], 1, [LENS + "a#packet=40"]),
        ("ranged", "", ["COR", "NIN", "RNG", "THF"], 3, [got[1][4][0]]),
    ]
    assert ask(con, "bestiary_jobs", zone=ZONE, name="Hydra's Wyvern") == []
