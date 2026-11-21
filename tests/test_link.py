from ffxi_extractors.capture import Packet
from ffxi_extractors.link import LINK_MS, Link

START, RELEASE, ZONE_IN = (0, 0x032), (0, 0x052), (0, 0x00A)


def at(idx, ms, key):
    return Packet(idx, ms, 0, key[0], key[1], 0, b"")


def test_a_start_links_until_a_release_and_for_a_while_after():
    link = Link()
    link.follow(START, at(1, 0, START), {"EventPara": 7}.get)
    assert link.at(500) == {"idx": 1, "event_id": 7}
    link.follow(RELEASE, at(2, 1000, RELEASE), {}.get)
    assert link.at(1000 + LINK_MS) == {"idx": 1, "event_id": 7}
    assert link.at(1001 + LINK_MS) is None


def test_a_zone_in_ends_the_event_and_starts_one_when_it_plays_a_cutscene():
    link = Link()
    link.follow(START, at(1, 0, START), {"EventPara": 7}.get)
    link.follow(ZONE_IN, at(2, 100, ZONE_IN), {}.get)
    assert link.open is None
    link.follow(ZONE_IN, at(3, 200, ZONE_IN), {"EventNum": 1, "EventPara": 9}.get)
    assert link.at(200) == {"idx": 3, "event_id": 9}
