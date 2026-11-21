"""Every packet extractor, by domain: battle, items, world, and progress. Each is a class; a run makes a
fresh one per capture. Derived facts are in ffxi_extractors.facts."""

from ffxi_extractors.extractors.battle.actions import Actions
from ffxi_extractors.extractors.battle.defeats import Defeats
from ffxi_extractors.extractors.battle.delay import Delay
from ffxi_extractors.extractors.battle.effects import Effects
from ffxi_extractors.extractors.battle.engages import Engages
from ffxi_extractors.extractors.battle.evasion import EvasionSkill
from ffxi_extractors.extractors.battle.fights import Fights
from ffxi_extractors.extractors.battle.hp import Hp
from ffxi_extractors.extractors.battle.immunity import Immunity
from ffxi_extractors.extractors.battle.kills import Kills
from ffxi_extractors.extractors.battle.mob_messages import MobMessages
from ffxi_extractors.extractors.items.digs import Digs
from ffxi_extractors.extractors.items.drops import Drops
from ffxi_extractors.extractors.items.fishing import Fishing
from ffxi_extractors.extractors.items.holdings import Holdings
from ffxi_extractors.extractors.items.obtained import Obtained
from ffxi_extractors.extractors.items.shops import Shops
from ffxi_extractors.extractors.items.synths import Synths
from ffxi_extractors.extractors.items.trades import Trades
from ffxi_extractors.extractors.progress.battlefields import Battlefields
from ffxi_extractors.extractors.progress.events import Events
from ffxi_extractors.extractors.progress.experience import Experience
from ffxi_extractors.extractors.progress.keyitems import KeyItems
from ffxi_extractors.extractors.world.character import Character
from ffxi_extractors.extractors.world.conquest import Conquest
from ffxi_extractors.extractors.world.entity_changes import EntityChanges
from ffxi_extractors.extractors.world.influence import Influence
from ffxi_extractors.extractors.world.levels import Levels
from ffxi_extractors.extractors.world.looks import Looks
from ffxi_extractors.extractors.world.party import Party
from ffxi_extractors.extractors.world.spawns import Spawns
from ffxi_extractors.extractors.world.weather import Weather
from ffxi_extractors.extractors.world.zones import Zones

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
