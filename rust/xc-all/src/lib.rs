//! Every Rust extractor: extractors/__init__.py's ALL. Its order does not change any output.

use xc_core::Extractor;

/// A fresh extractor of each kind, for one capture.
pub fn all() -> Vec<Box<dyn Extractor>> {
    vec![
        // B1 positions: engages, actions
        Box::new(xc_actions::Actions::default()),
        Box::new(xc_engages::Engages::default()),
        // B2 hp and effects
        Box::new(xc_hp::Hp::default()),
        Box::new(xc_effects::Effects::default()),
        // B3 combat rounds: delay, fights, kills, mob_messages, immunity, defeats, evasion_skill
        Box::new(xc_delay::Delay::default()),
        Box::new(xc_fights::Fights::default()),
        Box::new(xc_kills::Kills::default()),
        Box::new(xc_mob_messages::MobMessages::default()),
        Box::new(xc_immunity::Immunity::default()),
        Box::new(xc_defeats::Defeats::default()),
        Box::new(xc_evasion::EvasionSkill),
        // B4 events: events, obtained, keyitems, experience, battlefields
        Box::new(xc_events::Events::default()),
        Box::new(xc_obtained::Obtained::default()),
        Box::new(xc_keyitems::KeyItems::default()),
        Box::new(xc_experience::Experience::default()),
        Box::new(xc_battlefields::Battlefields::default()),
        // B5 items: fishing, digs, synths, drops, trades, holdings
        Box::new(xc_fishing::Fishing::default()),
        Box::new(xc_digs::Digs::default()),
        Box::new(xc_synths::Synths::default()),
        Box::new(xc_drops::Drops::default()),
        Box::new(xc_trades::Trades::default()),
        Box::new(xc_holdings::Holdings::default()),
        // B6 entities: looks, entity_changes, levels, spawns, weather, zones
        Box::new(xc_looks::Looks::default()),
        Box::new(xc_entity_changes::EntityChanges::default()),
        Box::new(xc_levels::Levels::default()),
        Box::new(xc_spawns::Spawns::default()),
        Box::new(xc_weather::Weather::default()),
        Box::new(xc_zones::Zones::default()),
        // B7 character and maps: character, party, conquest, influence, shops
        Box::new(xc_character::Character::default()),
        Box::new(xc_party::Party::default()),
        Box::new(xc_conquest::Conquest),
        Box::new(xc_influence::Influence),
        Box::new(xc_shops::Shops::default()),
    ]
}

/// The extractor of this name.
pub fn by_name(name: &str) -> Option<Box<dyn Extractor>> {
    all().into_iter().find(|x| x.meta().name == name)
}
