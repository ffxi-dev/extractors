"""The packets that place an entity: NPCs, mobs, and trusts (0x00E), other players (0x00D), HP% from those and
the party's (0x0DD, 0x0DF), the zone-in, which forgets them, and the character's own position (c2s 0x015).
actions and engages read them, as rust/xc-core's positions.rs keeps them."""

READS = frozenset({(0, 0x00A), (0, 0x00E), (0, 0x00D), (0, 0x0DD), (0, 0x0DF), (1, 0x015)})
