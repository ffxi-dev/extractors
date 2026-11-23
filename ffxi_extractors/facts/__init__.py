"""Every derived fact: ClickHouse SQL over the extractors' tables and each other's, run after them in the
same job, or over every capture at once by a rebuild."""

from ffxi_extractors.facts.aggro import Aggro, AggroPasses
from ffxi_extractors.facts.bestiary import Bestiary
from ffxi_extractors.facts.bestiary_looks import BestiaryLooks
from ffxi_extractors.facts.bestiary_mobs import BestiaryMobs
from ffxi_extractors.facts.exp_kills import ExpKills
from ffxi_extractors.facts.melee import Melee
from ffxi_extractors.facts.mob_events import MobEvents
from ffxi_extractors.facts.named_entities import NamedEntities
from ffxi_extractors.facts.npc_events import NpcEvents
from ffxi_extractors.facts.npc_shops import NpcShops
from ffxi_extractors.facts.npc_trades import NpcTrades
from ffxi_extractors.facts.recipes import Recipes
from ffxi_extractors.facts.steals import Steals
from ffxi_extractors.facts.tp_uses import TpUses

DERIVED = (
    NamedEntities,
    Bestiary,
    BestiaryMobs,
    Melee,
    TpUses,
    Steals,
    MobEvents,
    ExpKills,
    BestiaryLooks,
    Aggro,
    AggroPasses,
    NpcEvents,
    NpcTrades,
    NpcShops,
    Recipes,
)  # each after the units it reads
