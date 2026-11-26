# extractors Specification

## Purpose
How extractors read packets: through packets' layouts, by client version, with a field a packet lacks giving an unknown value, never a failed capture.

## Requirements

### Requirement: A short 0x00B gives no zone server
The zones extractor SHALL read 0x00B through ffxi_packets, and SHALL record no server when the packet ends before the address and port.

#### Scenario: A 0x00B with only its header
- **WHEN** a capture's 0x00B is four bytes and a zone-in follows
- **THEN** the zone-in is recorded with no server, and the capture does not fail

#### Scenario: A whole 0x00B
- **WHEN** a 0x00B with logout state 2 carries 10.20.30.40 and port 54230
- **THEN** the next zone-in's server is 10.20.30.40:54230

### Requirement: A capture's packets decode in its client version's layouts
The decoder SHALL pick each packet's layout as packets picks it, by the client version in the capture's header. A capture whose header names no client version (a PacketViewer import, a captain log's build) SHALL pick by the version live when its first packet was recorded.

#### Scenario: A party member before Master Levels
- **WHEN** YwMILwxCkmfL, recorded 2020-02-03 with no client version in its header, lists Yoran-Oran in a 0x0DD
- **THEN** the party row names Yoran-Oran, not ran-Oran: before 30211103_1 the name starts at 0x26

#### Scenario: A capture with a client version
- **WHEN** a capture's header names 30261102_1
- **THEN** its 0x0DD and 0x0E2 decode in today's layout, the name at 0x28

### Requirement: A TP move under Mighty Strikes says nothing of its crits
The bestiary SHALL give a TP move no hit and no crit when the same mob used Mighty Strikes (mob skill 688, 1008, 2242, or 2939) in the 50 s before it, since Mighty Strikes makes every hit crit for 45 s. A move's crit rate counts only the other uses.

#### Scenario: A crit 7 s after Mighty Strikes
- **WHEN** a mob's Slam Dunk crits 7 s after its Mighty Strikes (XKi5H7zHD9aJ, packets 56846 and 57050)
- **THEN** that use counts as neither a hit nor a crit of Slam Dunk

#### Scenario: A crit 60 s after
- **WHEN** a mob's move crits 60 s after its Mighty Strikes
- **THEN** it counts as a hit and a crit
