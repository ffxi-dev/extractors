# Spec Delta

## ADDED Requirements

### Requirement: A changed derived table keeps its rows when asked
`store.pending` SHALL list each derived unit whose table is of another engine, or holds a column its SQL dropped or retyped, and each unit that reads one. `setup(keep=True)` SHALL leave those tables as they are, rows and all, without reading their SQL, and the views as they are while any is listed; `setup()` SHALL make them again, empty.

#### Scenario: Scholar starts on a release that dropped a column
- **WHEN** bestiary_fights holds a column bestiary's SQL no longer makes and Scholar sets up with keep
- **THEN** bestiary_fights keeps its rows, and pending lists bestiary and bestiary_mobs until they are rebuilt

#### Scenario: A later fact reads a column the kept table lacks
- **WHEN** bestiary_fights is from before `tp.rules_out` and Scholar sets up with keep
- **THEN** setup does not fail on bestiary_mobs' SQL, and leaves both tables to the rebuild

### Requirement: A capture-row table sorted otherwise waits for its caller when asked
`store.sorts` SHALL list each decoder or extractor table made under another ORDER BY than the code's, with its ORDER BY and engine. `setup(keep=True)` SHALL leave such a table under its old ORDER BY; `setup()` SHALL copy and swap it as before. The bookkeeping tables SHALL be re-sorted by setup either way.

#### Scenario: kills made under an older ORDER BY
- **WHEN** kills is sorted otherwise and Scholar sets up with keep
- **THEN** kills keeps its rows and old ORDER BY, and sorts lists it until Scholar's rebuild swaps in a copy
