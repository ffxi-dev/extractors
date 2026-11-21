# Proposal

## Why

Party members each record the same fight. The bestiary counts it once by giving every copy the same `fight_key`: a hash of the world, the zone, the mob, the minute the fight ended, and an instance, which is the alliance roster, else the zone server, else the capture. On Scholar's archive (2026-11-21) the key splits copies of one fight more often than it should:

- **41,713 pairs** of fights in different captures, on the same mob in the same zone, end under 10 s apart in the same minute, yet have different keys. All are on the same world. 33,004 are on the same zone server; none on different servers; for 8,709 one side has no server. The likely cause: a recorder outside the claiming party saw the fight, so its roster differs, and the roster comes before the server.
- **1,907 pairs** split because their copies ended on either side of a minute, against 162,517 pairs the key matched.

Each split counts a fight twice on the mob pages: its HP, its drops, its TP moves.

## What Changes

- **Instance by zone server first.** The instance is the zone server when the capture knows it, else the roster, else the capture. Two captures on one zone server are on one instance by definition, so the 33,004 pairs match. A capture that began inside the zone has no server and keeps the roster, as now. Of the 173,875 pairs the key matches today, 18 have a server on one side only and would split; 33,004 would merge.
- **Not now: the minute.** A window on end times cannot tell copies from a mob's next fight: copies end a median 105 ms apart but up to 58.7 s, while one capture's next fight on the same mob id comes within 4.2 s for 1% of fights and 26 s for 10%. Matching copies by overlapping fight intervals across captures would fix the 1,907; it is a larger change to the key, the owners, and the rerolls, so it waits until the instance change shows what is left.

## Capabilities

### New Capabilities
- `fight-copies`: how the bestiary tells one fight's copies in several captures apart from different fights.

## Impact

- `facts/bestiary.py`: the instance's order in `fight_key`; `bestiary` and `bestiary_mobs` versions bump, so Scholar rebuilds both.
- Its pins on the fixtures move only if a fixture fight has both a roster and a server.
