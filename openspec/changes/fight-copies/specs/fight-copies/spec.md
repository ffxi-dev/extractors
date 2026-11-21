# Spec Delta

## ADDED Requirements

### Requirement: One fight, one count, whoever recorded it
The bestiary SHALL key each fight by the zone, the mob, the minute it ended, and its instance: the zone server when the capture knows it, else the alliance roster, else the capture. Copies with one key SHALL count once.

#### Scenario: Two parties on one zone server
- **WHEN** two captures on the same zone server, with different rosters, record the same mob's fight ending in the same minute
- **THEN** the mob pages count one fight

#### Scenario: A capture that began inside the zone
- **WHEN** two captures of one party have no zone server for the zone and record the same fight
- **THEN** the two copies match by roster, as before, since player ids are unique across servers

#### Scenario: One copy has a server and the other none
- **WHEN** one capture began inside the zone, so has no zone server, and its party member's copy has one
- **THEN** the copies count apart: the server comes first

#### Scenario: One capture names its world and the other none
- **WHEN** two captures on the same zone server record the same fight, and only one names its world
- **THEN** the mob pages count one fight: a zone server's address and a player's id each belong to one world
