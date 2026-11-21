"""Queries whose answers are known for the two fixtures. Run after every ClickHouse or packets bump: a wrong
answer here means the stack changed what Scholar says, not just how fast."""

import pytest
from conftest import value

ANSWERS = {
    "SELECT packets FROM captures WHERE capture_id = 'm'": 10687,
    "SELECT packets FROM captures WHERE capture_id = 'c'": 38828,
    "SELECT zone_id FROM zones WHERE capture_id = 'm'": 247,
    "SELECT count() FROM entity_changes WHERE capture_id = 'm'": 101,
    "SELECT count() FROM entity_changes WHERE capture_id = 'c'": 89,
    "SELECT uniqExact(entity_id) FROM entity_changes WHERE capture_id = 'c' AND name = 'Velociraptor'": 10,
    "SELECT concat(main_job, toString(main_level), '/', sub_job, toString(sub_level)) FROM character"
    " WHERE capture_id = 'c' ORDER BY idx LIMIT 1": "RDM99/BLM53",
    "SELECT countIf(claimed_by_party) FROM kills WHERE capture_id = 'c'": 10,  # 0x037 names it
    "SELECT item_id FROM character_gear WHERE capture_id = 'm' AND slot = 'main' ORDER BY idx LIMIT 1": 20595,
    # Packets of one opcode, and the first packet with a zone: the capture's first has none.
    "SELECT sum(packets) FROM sizes WHERE capture_id = 'm' AND direction = 's2c' AND opcode = 14": 5497,
    "SELECT min(idx) FROM zone_visits WHERE capture_id = 'c'": 1,
    # Combat: every action packet, Velociraptor fights and their HP, a mob's delay, and immunities.
    "SELECT count() FROM actions WHERE capture_id = 'c'": 1391,
    "SELECT count() FROM actions WHERE capture_id = 'c' AND category = 11": 38,
    "SELECT count() FROM fights WHERE capture_id = 'c' AND outcome = 'defeated'": 13,
    "SELECT count() FROM mob_hp WHERE capture_id = 'c'": 13,
    "SELECT concat(toString(hp_min), '~', toString(hp_max)) FROM mob_hp WHERE mob_id = 17301509": "3853~3926",
    "SELECT median(interval_ms) FROM attack_rounds WHERE capture_id = 'c' AND actor_is_mob": 4068.0,
    "SELECT count() FROM spell_results WHERE capture_id = 'c' AND outcome = 'immune'": 6,
    # Mob rounds with one target that survived them: every one counts toward multi-attack, 47 of them
    # with no interval (after a TP move or spell, or a mob's first in a life or in view). 62 are double
    # attacks.
    "SELECT count() FROM attack_rounds WHERE capture_id = 'c' AND actor_is_mob AND targets = 1"
    " AND NOT cut_short": 691,
    "SELECT count() FROM attack_rounds WHERE capture_id = 'c' AND actor_is_mob AND targets = 1"
    " AND NOT cut_short AND main_hand = 2": 62,
    "SELECT count() FROM attack_rounds WHERE capture_id = 'c' AND actor_is_mob AND targets = 1"
    " AND NOT cut_short AND interval_ms IS NULL": 47,
    "SELECT sum(misses) FROM attack_rounds WHERE capture_id = 'c' AND actor_is_mob": 601,
}


@pytest.mark.parametrize("sql", ANSWERS)
def test_known_answer(both, sql):
    assert value(both, sql) == ANSWERS[sql]
