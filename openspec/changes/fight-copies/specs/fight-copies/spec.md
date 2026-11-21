# Spec Delta

## ADDED Requirements

### Requirement: One fight, one count, whoever recorded it
The bestiary SHALL key each fight by the world, the zone, the mob, the minute it ended, and its instance: the zone server when the capture knows it, else the alliance roster, else the capture. Copies with one key SHALL count once.

#### Scenario: Two parties on one zone server
- **WHEN** two captures on the same zone server, with different rosters, record the same mob's fight ending in the same minute
- **THEN** the mob pages count one fight

#### Scenario: A capture that began inside the zone
- **WHEN** a capture has no zone server for the zone and its party recorded the fight in another capture
- **THEN** the two copies match by roster, as before
