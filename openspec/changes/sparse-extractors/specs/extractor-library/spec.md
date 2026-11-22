# Spec Delta

## ADDED Requirements

### Requirement: An extractor says whether a capture without its packets gives it rows
Each extractor SHALL say, as `sparse`, whether its rows come only from its reads outside the world's. A sparse extractor SHALL write no row from a capture that holds none of those packets, and the library's tests SHALL walk the fixtures once per sparse extractor with its own packets left out and find no rows.

#### Scenario: Synthesis on a capture with no synthesis
- **WHEN** a capture holds no 0x06F or 0x070
- **THEN** walking it with synths gives no rows

#### Scenario: Zones is not sparse
- **WHEN** a capture holds zone-ins (0x00A, the world's) but no 0x00B
- **THEN** zones still writes its rows, and zones is not sparse
