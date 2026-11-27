# Spec Delta

## ADDED Requirements

### Requirement: A changed derived table keeps its rows when asked
`store.pending` SHALL list each derived unit whose table is of another engine, or holds a column its SQL dropped or retyped. `setup(keep=True)` SHALL leave such a table as it is, rows and all; `setup()` SHALL make it again, empty.

#### Scenario: Scholar starts on a release that dropped a column
- **WHEN** bestiary_fights holds a column bestiary's SQL no longer makes and Scholar sets up with keep
- **THEN** bestiary_fights keeps its rows, and pending lists bestiary until it is rebuilt
