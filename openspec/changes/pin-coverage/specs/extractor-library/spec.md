# Spec Delta

## MODIFIED Requirements

### Requirement: An output change needs a version
The library SHALL pin each unit's output on the fixtures to its `version`, and its CI SHALL fail when a unit's output changes without a new version. Every table a unit writes SHALL have rows on at least one fixture, and CI SHALL fail when one has none.

#### Scenario: A change without a bump
- **WHEN** a pull request changes what an extractor or derived fact writes and leaves its `version`
- **THEN** CI fails, naming the unit

#### Scenario: A table the fixtures leave empty
- **WHEN** a unit's table has no rows on any fixture
- **THEN** CI fails, naming the unit and the table, until a small public capture that fills it joins the fixtures

## ADDED Requirements

### Requirement: A release is checked against the last release
Before a release, the library's Rust rows on the parity sample SHALL be compared with the last release's, each sample capture read at the sha256 it was pinned at, and the check SHALL fail for a unit whose rows differ while its version and the decoder's are as they were in that release.

#### Scenario: Rows that changed without a bump
- **WHEN** `parity --against <the last tag> all` finds a unit's rows on a sample capture differ from the tag's, and the unit's version is the tag's
- **THEN** it prints the rows each way, says to bump the unit, and exits 1

#### Scenario: Rows that changed with a bump
- **WHEN** the rows differ and the unit's version is new
- **THEN** it prints the rows each way and does not fail
