//! Every Rust extractor: extractors/__init__.py's ALL. Its order does not change any output.

use xc_core::Extractor;

/// A fresh extractor of each kind, for one capture.
pub fn all() -> Vec<Box<dyn Extractor>> {
    vec![
        // B1 positions: engages, actions
        Box::new(xc_actions::Actions::default()),
        Box::new(xc_engages::Engages::default()),
        // B2 hp and effects
        // B3 combat rounds: delay, fights, kills, mob_messages, immunity, defeats, evasion_skill
        // B4 events: events, obtained, keyitems, experience, battlefields
        // B5 items: fishing, digs, synths, drops, trades, holdings
        // B6 entities: looks, entity_changes, levels, spawns, weather, zones
        // B7 character and maps: character, party, conquest, influence, shops
    ]
}

/// The extractor of this name.
pub fn by_name(name: &str) -> Option<Box<dyn Extractor>> {
    all().into_iter().find(|x| x.meta().name == name)
}
