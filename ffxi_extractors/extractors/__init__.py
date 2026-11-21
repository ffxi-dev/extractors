"""Every extractor. Each is a class; a run makes a fresh one per capture."""

from .actions import Actions
from .aggro import Aggro, AggroPasses
from .battlefields import Battlefields
from .bestiary import Bestiary
from .bestiary_looks import BestiaryLooks
from .bestiary_mobs import BestiaryMobs
from .character import Character
from .conquest import Conquest
from .defeats import Defeats
from .delay import Delay
from .digs import Digs
from .drops import Drops
from .effects import Effects
from .engages import Engages
from .entity_changes import EntityChanges
from .evasion import EvasionSkill
from .events import Events
from .exp_kills import ExpKills
from .experience import Experience
from .fights import Fights
from .fishing import Fishing
from .holdings import Holdings
from .hp import Hp
from .immunity import Immunity
from .influence import Influence
from .keyitems import KeyItems
from .kills import Kills
from .levels import Levels
from .looks import Looks
from .melee import Melee
from .mob_events import MobEvents
from .mob_messages import MobMessages
from .npc_events import NpcEvents
from .npc_shops import NpcShops
from .npc_trades import NpcTrades
from .obtained import Obtained
from .party import Party
from .shops import Shops
from .spawns import Spawns
from .steals import Steals
from .synths import Synths
from .tp_uses import TpUses
from .trades import Trades
from .weather import Weather
from .zones import Zones

ALL = (
    Zones,
    EntityChanges,
    Character,
    EvasionSkill,
    Party,
    Actions,
    Fights,
    Delay,
    Immunity,
    Hp,
    Events,
    KeyItems,
    Kills,
    Drops,
    Obtained,
    Holdings,
    Spawns,
    Levels,
    Weather,
    Conquest,
    Influence,
    Digs,
    Fishing,
    Synths,
    Effects,
    Defeats,
    MobMessages,
    Battlefields,
    Experience,
    Looks,
    Engages,
    Trades,
    Shops,
)

# Facts over other units' rows, in ClickHouse SQL: run after them in the same job, or by a rebuild.
DERIVED = (
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
)  # each after the units it reads
