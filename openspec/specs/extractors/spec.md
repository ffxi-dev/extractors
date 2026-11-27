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

### Requirement: A mob page reads its job signs
The bestiary_jobs page query SHALL give, per card (model), each sign a mob's kept fights show of a job: Double Attack (3 or more of 30 or more rounds whose first swing hit swung twice), Triple Attack (2 or more of 30 rounds swung 3 or more times), Zanshin (the mob card's Possible Zanshin rule), fists or two weapons (an off-hand swing in half of 20 rounds), Kick Attacks (3 or more kicks, 3% of 30 rounds), Guard and Counter (3 or more, 1% of 200 swings at it), a "Resist!" to a status, each spell it cast, the fast_cast view's mob, and each job's two-hour or ability it used. A double or triple in over 60% of rounds is the mob's kind's attack and gives no sign. Each sign SHALL name the jobs that give it at the mob's top level (BG Wiki's job traits, blue magic left out; a spell's jobs from retail-resources' spells, as spell_jobs), its count and its chances, and up to 3 of its packets as Lens links. A resist trait no job holds names none.

#### Scenario: Ark Angel MR
- **WHEN** a mob swings 3 times in 95 of 2,114 rounds, meets Gravity and Slow with "Resist!", and uses Perfect Dodge and Charm
- **THEN** its signs are Triple Attack (THF), Resist Gravity (THF), Resist Slow (BST, PUP, SMN, DNC), Perfect Dodge (THF), and Charm (BST), each with its packets

#### Scenario: A party member's copy
- **WHEN** two recorders upload one fight
- **THEN** its rounds count once, from the kept copy

#### Scenario: Dual Wield's level
- **WHEN** a level 20 mob swings an off hand every round
- **THEN** the sign names DNC, MNK, NIN, and PUP, not THF, whose Dual Wield comes at 83

### Requirement: Names give each spell's jobs
The names load SHALL keep, for each release, each spell's jobs and the level each learns it at (spells' level_required, MON left out), as names of kind spell_job, which the spell_jobs view reads: release, id, job, level.

#### Scenario: Protect
- **WHEN** a release lists Protect at WHM 7, RDM 7, and PLD 10
- **THEN** spell_jobs has those three rows for it
