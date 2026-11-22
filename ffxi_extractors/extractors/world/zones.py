import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Zones(Extractor):
    name = "zones"
    version = 3  # 2: server; 3: through ffxi_packets, none from a short 0x00B
    doc = "Each zone-in: the zone the character entered, when, and on which zone server."
    reads = frozenset({(0, 0x00A), (0, 0x00B)})
    sparse = False  # a zone-in, the world's 0x00A, is a row
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
