# Spec Delta

## ADDED Requirements

### Requirement: The pages' queries across captures are the library's
The library SHALL hold each query a page across captures runs over the derived facts, one file in `sql/pages/` with its blanks as ClickHouse parameters, and the tests that check what it answers. A caller SHALL run a query by its file's name.

#### Scenario: A change to a derived fact breaks a page
- **WHEN** a change to a derived fact changes what a mob page's query answers
- **THEN** the library's own tests fail, before a release
