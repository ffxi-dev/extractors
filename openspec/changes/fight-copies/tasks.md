# Tasks

## 0. Owner

- [x] 0.1 Approve the instance order (server, roster, capture), and leaving the minute for now (owner, 2026-11-21: player ids are unique across servers, so the roster is a sound fallback)

## 1. Instance by server

- [x] 1.1 `fight_key`'s instance: the zone server first, then the roster, then the capture; `bestiary` 22
- [x] 1.2 Tests: two captures on one zone server with different rosters share a key; two with no server and one roster still do
- [x] 1.4 `ffxi-packets` 2.0.0; every pin holds, and bestiary v22 gives the fixtures the same rows as v21
- [ ] 1.3 After Scholar's rebuild, the archive's pairs split on one server: from 33,004 to none

## 2. Then

- [ ] 2.1 Measure the pairs still split, by cause, and decide on matching by overlapping intervals
