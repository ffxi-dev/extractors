# Spec Delta

## ADDED Requirements

### Requirement: A capture's rows are read by its id
An extractor table that its readers filter by capture SHALL be sorted by capture first. `setup` SHALL copy a table made under another ORDER BY into one sorted as the code says, with its rows, and swap it in, once.

#### Scenario: entity_changes made under the old order
- **WHEN** setup finds entity_changes sorted by entity first
- **THEN** it holds the same rows sorted by capture first, and a second setup leaves it
