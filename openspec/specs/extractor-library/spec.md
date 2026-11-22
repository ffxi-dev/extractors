# extractor-library Specification

## Purpose
The library holds every extractor and derived fact, lets anyone run and change them without Vault access, and reaches Scholar by a tagged release. Design: ffxi-dev/vault's open-extractors change.

## Requirements

### Requirement: The analyses live in their own repository
Every extractor and derived fact, their contract, the schema, the SQL functions and views, a one-capture indexer, and the names loader SHALL live in `ffxi-dev/extractors` under GPL-3.0, with their tests, their pinned outputs, and fixtures taken only from public Mogsafe captures. It SHALL start private and become public only once the owner has read it.

#### Scenario: Before the owner has read it
- **WHEN** the library is set up and the owner has not yet read its layout
- **THEN** the repository is private

### Requirement: The library holds nothing of the service
The library SHALL hold nothing of Scholar's service: its feed, jobs, mirror, rebuild, pages, web view, API, auth, MCP, search, health, or telemetry.

#### Scenario: Nothing of the service
- **WHEN** the repository is searched for Scholar's API, Clerk, Mogsafe client, or page code, a host other than public ones, or a credential
- **THEN** none is found

### Requirement: A contributor works with no Vault access
Once public, the repository SHALL run its tests, its pins, and its indexer from a clean clone with no credentials, against a ClickHouse its own compose file starts at the version Scholar pins.

#### Scenario: A clean clone
- **WHEN** someone with no Vault access follows the README's quick start
- **THEN** the tests pass, and the fixtures are indexed into their local ClickHouse with names

#### Scenario: A real capture
- **WHEN** a contributor downloads a capture from Mogsafe's `/c/<id>` and indexes it
- **THEN** every extractor and derived fact writes its rows for it

### Requirement: An output change needs a version
The library SHALL pin each unit's output on the fixtures to its `version`, and its CI SHALL fail when a unit's output changes without a new version.

#### Scenario: A change without a bump
- **WHEN** a pull request changes what an extractor or derived fact writes and leaves its `version`
- **THEN** CI fails, naming the unit

### Requirement: Scholar runs a tagged release
Scholar SHALL install the library by release tag and keep no copy of its code. Moving the pin SHALL re-run only the units whose versions changed.

#### Scenario: The move itself
- **WHEN** Scholar first deploys on the library, with every unit at the version it had
- **THEN** no capture is re-run

#### Scenario: A contribution ships
- **WHEN** a release bumps one derived fact's version and Scholar's pin moves to it
- **THEN** Scholar re-runs that fact over the archive, and nothing else

### Requirement: The pages' queries across captures are the library's
The library SHALL hold each query a page across captures runs over the derived facts, one file in `sql/pages/` with its blanks as ClickHouse parameters, and the tests that check what it answers. A caller SHALL run a query by its file's name.

#### Scenario: A change to a derived fact breaks a page
- **WHEN** a change to a derived fact changes what a mob page's query answers
- **THEN** the library's own tests fail, before a release

### Requirement: A capture's rows are read by its id
An extractor table that its readers filter by capture SHALL be sorted by capture first. `setup` SHALL copy a table made under another ORDER BY into one sorted as the code says, with its rows, and swap it in, once.

#### Scenario: entity_changes made under the old order
- **WHEN** setup finds entity_changes sorted by entity first
- **THEN** it holds the same rows sorted by capture first, and a second setup leaves it

### Requirement: A name lookup gives one name, the same every time
Each `*_names` view SHALL give one name per release and id, read from `names_one`, which the names loader builds beside `names` with no query grouping names. Where a release lists an id under two names, the view SHALL give the least. `party_names` SHALL give a member one name at a capture's start: the party's, or the capture's character when the party never names it.

#### Scenario: An id a release names two ways
- **WHEN** a release lists an entity id as both Modest Coffer and Capacious Coffer
- **THEN** entity_names gives Capacious Coffer, in whatever order the release lists them

#### Scenario: A recorder the party names otherwise
- **WHEN** the party names the recorder misha and the capture names its character Damisha
- **THEN** party_names gives misha at idx 0, and nothing else there
