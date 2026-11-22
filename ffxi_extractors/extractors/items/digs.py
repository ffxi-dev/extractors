import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table
from ffxi_extractors.extractors.items.gathering import HELD, PLACE


class Digs(Extractor):
    """The character's chocobo digs. The client asks with 0x063 after the dig's animation (0x02F, which the
    zone sends for anyone's dig and which carries no result). The zone answers in its own dialog:
    'Obtained: <item>' is a 0x02A whose first number is the item, among other 0x02A lines (the dig's hints,
    the conquest points a cache gives) whose numbers are not items; 'You dig and you dig, but find nothing'
    is a 0x036. Which message is which differs by zone, so the item found is the one a 0x02A named that also
    entered the inventory."""

    name = "digs"
    version = 1
    doc = "Each chocobo dig the character made: where, in what weather and Vana'diel time, and what it found."
    reads = HELD | {(0, 0x00A), (1, 0x063), (0, 0x02A)}
    tables = (
        Table(
            "digs",
            "One row per dig the character asked for (0x063). A dig whose item the inventory could not take"
            " (thrown away) reads as nothing found.",
            (
                *PLACE,
                Column(
                    "item_id",
                    pa.int32(),
                    "What it found: the item an 'Obtained' message (0x02A) named and the inventory gained"
                    " under 3 s after; none when it found nothing. A raised chocobo's second find is left"
                    " out.",
                ),
            ),
        ),
    )
