# Spec Delta

## MODIFIED Requirements

### Requirement: A short 0x00B gives no zone server
The zones extractor SHALL read 0x00B through packets' layouts (rust/xc-decode), and SHALL record no server when the packet ends before the address and port.

#### Scenario: A 0x00B with only its header
- **WHEN** a capture's 0x00B is four bytes and a zone-in follows
- **THEN** the zone-in is recorded with no server, and the capture does not fail

#### Scenario: A whole 0x00B
- **WHEN** a 0x00B with logout state 2 carries 10.20.30.40 and port 54230
- **THEN** the next zone-in's server is 10.20.30.40:54230
