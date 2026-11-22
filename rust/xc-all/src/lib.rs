//! Every Rust extractor: extractors/__init__.py's ALL. Its order does not change any output.

use xc_core::Extractor;

/// A fresh extractor of each kind, for one capture.
pub fn all() -> Vec<Box<dyn Extractor>> {
    vec![
        // B1 positions: engages, actions
        Box::new(xc_actions::Actions::default()),
        // B2 hp and effects
        // B3 combat rounds: delay, fights, kills, mob_messages, immunity, defeats, evasion_skill
        // B4 events: events, obtained, keyitems, experience, battlefields
        Box::new(xc_events::Events::default()),
        Box::new(xc_obtained::Obtained::default()),
        Box::new(xc_keyitems::KeyItems::default()),
        Box::new(xc_experience::Experience::default()),
        Box::new(xc_battlefields::Battlefields::default()),
        // B5 items: fishing, digs, synths, drops, trades, holdings
        // B6 entities: looks, entity_changes, levels, spawns, weather, zones
        // B7 character and maps: character, party, conquest, influence, shops
    ]
}

/// The extractor of this name.
pub fn by_name(name: &str) -> Option<Box<dyn Extractor>> {
    all().into_iter().find(|x| x.meta().name == name)
}
