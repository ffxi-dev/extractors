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
