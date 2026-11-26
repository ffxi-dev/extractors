import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class Shops(Extractor):
    """NPC and guild shops: what each lists at what price (0x03C, guild 0x083 and 0x085 with stock), when
    it opened (0x03E, guild 0x086), and what the character bought (c2s 0x083, guild c2s 0x0AA). No packet
    names the shop's NPC. An NPC shop's is the one whose event the character answered (c2s 0x05B) up to 10
    s before, until its release (0x052) or another NPC's answer, else the one last talked to (c2s 0x01A) or
    whose event started: Regine's menu opens her shop though the character may talk to another NPC meanwhile.
    A guild's is the one talked to when it opened (0x086): the client asks for a guild's lists from its menu.
    Prices move with fame, which no packet carries, and with the nation's conquest standing for some shops:
    each row keeps the character's nation, rank, and the nation's standing."""

    name = "shops"
    version = 2
    doc = "NPC and guild shops: stock and prices with the character's nation and rank, openings, purchases."
    reads = frozenset(
        {(1, 0x01A), (0, 0x032), (0, 0x034), (0, 0x036), (1, 0x05B), (0, 0x052), (0, 0x061), (0, 0x05E),
         (0, 0x03E), (0, 0x03C), (1, 0x083),
         (0, 0x03F), (0, 0x086), (0, 0x083), (0, 0x085), (1, 0x0AA), (0, 0x082)}
    )  # fmt: skip
    tables = (
        Table(
            "shop_items",
            "One row per item a shop list showed: an NPC shop's (0x03C), or a guild's, with its stock: what"
            " it sells (0x083) and what it buys (0x085). A guild sends its list each time it is opened, so"
            " its stock is kept with the time of each.",
            (
                Column("kind", pa.string(), "shop, guild_sells, or guild_buys."),
                Column(
                    "npc_id",
                    pa.int64(),
                    "The shop's NPC: the one whose event the character answered, else last talked to; a"
                    " guild's, the one talked to when it opened.",
                ),
                Column("list_idx", pa.int64(), "The list's first packet: one opening of the shop."),
                Column("item_id", pa.int32(), "The item."),
                Column("price", pa.int64(), "Its price in gil, as the server sent it to this character."),
                Column("shop_index", pa.int32(), "Its place in an NPC shop's list (ShopIndex)."),
                Column("stock", pa.int32(), "A guild's stock of it (Count)."),
                Column("max", pa.int32(), "A guild's most stock of it (Max)."),
                Column("skill", pa.int32(), "An NPC shop's Skill field, as sent."),
                Column("guild_info", pa.int32(), "An NPC shop's GuildInfo field, as sent."),
                Column(
                    "nation",
                    pa.string(),
                    "The character's nation, from its last status (0x061); none before the first.",
                ),
                Column("nation_rank", pa.int32(), "The character's rank in its nation (0x061)."),
                Column(
                    "conquest_rank",
                    pa.int32(),
                    "The character's nation's conquest standing, 1 to 3, from the last conquest map (0x05E).",
                ),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
        Table(
            "shop_actions",
            "One row per shop opened (0x03E), guild shop opened or closed (0x086), and purchase: from an NPC"
            " shop (c2s 0x083, with the server's answer 0x03F) or a guild (c2s 0x0AA, answer 0x082).",
            (
                Column("action", pa.string(), "open, guild, buy, or guild_buy."),
                Column("npc_id", pa.int64(), "The shop's NPC, as shop_items names it."),
                Column("items", pa.int32(), "For open: how many items the shop lists (ShopListNum)."),
                Column("item_id", pa.int32(), "For a purchase: the item, from the list or the packet."),
                Column("quantity", pa.int64(), "For a purchase: how many the character asked for."),
                Column("price", pa.int64(), "For a purchase: the item's price in the last list, each."),
                Column(
                    "bought",
                    pa.int64(),
                    "For a purchase: how many the server says were bought (0x03F Count, 0x082 Trade).",
                ),
                Column("buy_state", pa.int32(), "For an NPC shop purchase: 0x03F's BuyState, as sent."),
                Column("stock", pa.int32(), "For a guild purchase: the guild's stock after (0x082 Count)."),
                Column("guild_status", pa.int32(), "For guild: 0x086's Stat, 0 open, 1 closed, 2 holiday."),
                Column("guild_time", pa.int64(), "For guild: 0x086's Time, as sent."),
                Column(
                    "open_hour",
                    pa.int32(),
                    "For guild: the Vana'diel hour it opens, from Time; retail sends it only while closed.",
                ),
                Column("close_hour", pa.int32(), "For guild: the hour it closes."),
                Column("zone_id", pa.int32(), "The zone."),
            ),
        ),
    )
