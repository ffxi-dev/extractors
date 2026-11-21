"""What a capture's packets say about the world so far, as captain's backend reads it from the client:
the zone and its weather, the recording character and where it stands, its party, its inventory, and the
entities around it."""

from __future__ import annotations

from ffxi_extractors.capture import Capture, Fields, Packet

S2C, C2S = 0, 1
# The packets update() reads. Every run decodes them, beside its extractors' own; WORLD_VERSION changes
# whenever what update() keeps does, and re-runs every unit.
WORLD = frozenset(
    {
        *((S2C, op) for op in (0x00A, 0x00E, 0x037, 0x0DD, 0x0E2, 0x0C8, 0x01E, 0x01F, 0x020, 0x057)),
        (C2S, 0x015),
    }
)
WORLD_VERSION = 2  # 2: the character's position and the zone's weather


def zone_of(entity_id: int | None) -> int | None:
    """An NPC or mob id holds its zone in bits 12 to 23, as LSB reads it; a player's id does not."""
    if entity_id is None or entity_id < 0x1000000:
        return None
    return (entity_id >> 12) & 0xFFF


class World:
    def __init__(self, cap: Capture):
        self.zone: int | None = None
        self.character_id = cap.character_id
        self.character = cap.character
        self.party: set[int] = set()  # party and alliance member ids
        self.entities: dict[int, dict] = {}  # act index -> {"id", "name"}
        self.items: dict[tuple[int, int], int] = {}  # (container, index) -> item id
        self.pos: tuple = (None, None, None)  # the character's last position: c2s 0x015, the zone-in
        self.pos_ms = 0  # when it came
        self.weather: int | None = None  # the zone's weather: the zone-in, 0x057

    @property
    def here(self) -> tuple | None:
        """The character's position, when the packets gave all three coordinates."""
        return self.pos if None not in self.pos else None

    def update(self, p: Packet, f: Fields) -> None:
        if p.channel != 0:
            return
        op = p.opcode
        if p.direction == C2S:
            if op == 0x015:  # the character's own position
                self.pos, self.pos_ms = (f("x"), f("y"), f("z")), p.ts_ms
            return
        if op == 0x00A:  # zone-in
            self.zone = f("ZoneNo")
            self.entities.clear()
            self.character_id = f("PosHead.UniqueNo") or self.character_id
            self.character = f("name") or self.character
            self.pos, self.pos_ms = (f("PosHead.x"), f("PosHead.y"), f("PosHead.z")), p.ts_ms
            self.weather = f("WeatherNumber")
        elif op == 0x057:  # the zone's weather changed
            self.weather = f("WeatherNumber")
        elif op == 0x037:  # the character's own status: a captain log has no zone-in to name it
            self.character_id = f("UniqueNo") or self.character_id
        elif op == 0x00E:  # NPC or mob update
            uid = f("UniqueNo")
            if self.zone is None:
                self.zone = zone_of(uid)
            index = f("ActIndex")
            if index is None:
                return
            e = self.entities.setdefault(index, {})
            if e.get("id") != uid:
                e.clear()
                e["id"] = uid
            if name := f("Data.name"):
                e["name"] = name
            if f("SendFlg.Despawn"):
                self.entities.pop(index, None)
        elif op in (0x0DD, 0x0E2):  # a party or alliance member
            if (uid := f("UniqueNo")) is not None:
                self.party.add(uid)
        elif op == 0x0C8:  # the whole party and alliance: who left is gone from it
            members = [f(f"GroupTbl[{i}].UniqueNo") for i in range(20)]
            if any(m is not None for m in members):
                self.party = {m for m in members if m}
        elif op in (0x01E, 0x01F, 0x020):  # an inventory slot: 0x01E sends its quantity, not its item
            key = (f("Category"), f("ItemIndex"))
            if not f("ItemNum"):
                self.items.pop(key, None)
            elif op != 0x01E:
                self.items[key] = f("ItemNo")

    def claimed_by_party(self, claim_id: int | None) -> bool:
        return claim_id is not None and (claim_id == self.character_id or claim_id in self.party)
