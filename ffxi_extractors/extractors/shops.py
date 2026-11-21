import pyarrow as pa

from ..extract import Column, Extractor, Table

GUILD_LISTS = {0x083: "guild_sells", 0x085: "guild_buys"}  # what the guild sells to the character, and buys
NATIONS = ("San d'Oria", "Bastok", "Windurst")  # 0x061's nation, and the order of 0x05E's balance


def hours(stat: int | None, time: int | None) -> tuple[int | None, int | None]:
    """A guild's opening hours from 0x086, as LSB packs them: bits open to close - 1 of Time set, bit 31 to
    keep the client quiet. Retail sends them only while the guild is closed (Stat 1); while it is open, Time
    holds whatever was in the buffer."""
    if stat != 1 or not time:
        return None, None
    bits = [h for h in range(24) if time >> h & 1]
    if not bits or bits != list(range(bits[0], bits[-1] + 1)):
        return None, None
    return bits[0], bits[-1] + 1


class Shops(Extractor):
    """NPC and guild shops: what each lists at what price (0x03C, guild 0x083 and 0x085 with stock), when
    it opened (0x03E, guild 0x086), and what the character bought (c2s 0x083, guild c2s 0x0AA). No packet
    names the shop's NPC: it is the one the character last talked to (c2s 0x01A) or whose event is under way.
    Prices move with fame, which no packet carries, and with the nation's conquest standing for some shops:
    each row keeps the character's nation, rank, and the nation's standing."""

    name = "shops"
    version = 1
    doc = "NPC and guild shops: stock and prices with the character's nation and rank, openings, purchases."
    reads = frozenset(
        {(1, 0x01A), (0, 0x032), (0, 0x034), (0, 0x061), (0, 0x05E), (0, 0x03E), (0, 0x03C), (1, 0x083),
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
                Column("npc_id", pa.int64(), "The shop's NPC: the one last talked to, or whose event is on."),
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

    def __init__(self):
        self.npc: int | None = None
        self.nation = self.rank = self.balance = None
        self.list: dict[int, tuple[int, int]] = {}  # an NPC shop's list: shop index -> (item, price)
        self.list_idx: int | None = None
        self.guild: dict[int, dict] = {}  # guild list opcode -> {"idx", "prices": {item: price}}
        self.buy: dict | None = None  # the purchase the server has yet to answer

    def packet(self, p, f, world, emit):
        key = (p.direction, p.opcode)
        if key == (1, 0x01A):
            if not f("ActionID"):  # talk
                self.npc = f("UniqueNo")
        elif key in ((0, 0x032), (0, 0x034)):
            self.npc = f("UniqueNo")
        elif key == (0, 0x061):
            self.nation, self.rank = f("statusdata.nation"), f("statusdata.rank")
        elif key == (0, 0x05E):
            self.balance = f("Conquest.Balance")
        elif key == (0, 0x03E):
            self.list, self.list_idx = {}, p.idx
            self._act(emit, p, world, "open", items=f("ShopListNum"))
        elif key == (0, 0x03C):
            self._shop_list(p, f, world, emit)
        elif key in ((0, 0x083), (0, 0x085)):
            self._guild_list(p, f, world, emit)
        elif key == (0, 0x086):
            stat, time = f("Stat"), f("Time")
            open_hour, close_hour = hours(stat, time)
            self._act(emit, p, world, "guild", guild_status=stat, guild_time=time, open_hour=open_hour,
                      close_hour=close_hour)  # fmt: skip
        elif key == (1, 0x083):
            item, price = self.list.get(f("ShopItemIndex"), (None, None))
            self.buy = self._act(emit, p, world, "buy", item_id=item, quantity=f("ItemNum"), price=price)
        elif key == (0, 0x03F):
            if self.buy and self.buy["action"] == "buy":
                self.buy.update(bought=f("Count"), buy_state=f("BuyState"))
            self.buy = None
        elif key == (1, 0x0AA):
            item = f("ItemNo")
            price = self.guild.get(0x083, {}).get("prices", {}).get(item)
            self.buy = self._act(emit, p, world, "guild_buy", item_id=item, quantity=f("ItemNum"),
                                 price=price)  # fmt: skip
        elif key == (0, 0x082):
            if self.buy and self.buy["action"] == "guild_buy" and f("ItemNo") == self.buy["item_id"]:
                self.buy.update(bought=f("Trade"), stock=f("Count"))
            self.buy = None

    def _act(self, emit, p, world, action, **values):
        return emit("shop_actions", p, action=action, npc_id=self.npc, zone_id=world.zone, **values)

    def _standing(self) -> dict:
        nation = NATIONS[self.nation] if self.nation is not None and self.nation < 3 else None
        rank = self.balance >> (2 * self.nation) & 3 if nation and self.balance is not None else None
        return {"nation": nation, "nation_rank": self.rank, "conquest_rank": rank, "npc_id": self.npc}

    def _shop_list(self, p, f, world, emit):
        if self.list_idx is None:
            self.list_idx = p.idx
        for i in range(19):  # up to 19 a packet, as LSB sends them
            t = f"ShopItemTbl[{i}]."
            item = f(t + "ItemNo")
            if not item:
                continue
            price, index = f(t + "ItemPrice"), f(t + "ShopIndex")
            self.list[index] = (item, price)
            emit("shop_items", p, kind="shop", list_idx=self.list_idx, item_id=item, price=price,
                 shop_index=index, skill=f(t + "Skill"), guild_info=f(t + "GuildInfo"), zone_id=world.zone,
                 **self._standing())  # fmt: skip

    def _guild_list(self, p, f, world, emit):
        stat = f("Stat") or 0
        g = self.guild.get(p.opcode)
        if g is None or stat & 0x3F == 0:  # a list's first packet: 0x40 of several, 0x80 of one
            g = self.guild[p.opcode] = {"idx": p.idx, "prices": {}}
        for i in range(min(f("Count") or 0, 30)):
            t = f"List[{i}]."
            item = f(t + "ItemNo")
            if not item:
                continue
            g["prices"][item] = f(t + "Price")
            emit("shop_items", p, kind=GUILD_LISTS[p.opcode], list_idx=g["idx"], item_id=item,
                 price=f(t + "Price"), stock=f(t + "Count"), max=f(t + "Max"), zone_id=world.zone,
                 **self._standing())  # fmt: skip
