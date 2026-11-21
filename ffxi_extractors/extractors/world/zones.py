import pyarrow as pa

from ffxi_extractors.extract import Column, Emit, Extractor, Fields, Packet, Table, World


def server(f) -> str | None:
    """The zone server 0x00B points the client to: its IPv4 address (Iwasaki[0-3]) and port (Iwasaki[4-5],
    little endian); none when the packet ends before them. The bytes after it vary with the session."""
    b = [f(f"Iwasaki[{i}]") for i in range(6)]
    return None if None in b else f"{'.'.join(map(str, b[:4]))}:{b[4] | b[5] << 8}"


class Zones(Extractor):
    name = "zones"
    version = 3  # 2: server; 3: through ffxi_packets, none from a short 0x00B
    doc = "Each zone-in: the zone the character entered, when, and on which zone server."
    reads = frozenset({(0, 0x00A), (0, 0x00B)})
    tables = (
        Table(
            "zones",
            "One row per zone-in (0x00A).",
            (
                Column(
                    "zone_id", pa.int32(), "The zone entered, as retail-resources' zones table numbers it."
                ),
                Column(
                    "server",
                    pa.string(),
                    "The zone server, address:port, from the 0x00B that sent the character there; none for"
                    " a capture's first zone-in after login. Parallel instances of a zone run on different"
                    " servers.",
                ),
            ),
        ),
    )

    def __init__(self):
        self.next: str | None = None

    def packet(self, p: Packet, f: Fields, world: World, emit: Emit) -> None:
        if p.opcode == 0x00B:  # LogoutState 2 is a zone change; a logout's next zone-in comes via the lobby
            self.next = server(f) if f("LogoutState") == 2 else None
            return
        emit("zones", p, zone_id=f("ZoneNo"), server=self.next)
        self.next = None
