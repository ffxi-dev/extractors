"""The event a change follows: what an event's packets are, and the one under way."""

# (direction, opcode) -> kind
KINDS = {
    (0, 0x032): "start",
    (0, 0x033): "start",
    (0, 0x034): "start",
    (0, 0x05C): "update",
    (0, 0x05D): "update",
    (1, 0x05B): "reply",
    (1, 0x05C): "reply",
    (0, 0x052): "release",
    (0, 0x036): "message",
    (0, 0x027): "message",
    (0, 0x02A): "message",
    (0, 0x053): "message",
}


LINK_MS = 30_000  # a log change this soon after an event's last packet follows from it


class Link:
    """The event a change follows: the one under way, or one whose last packet came at most LINK_MS before.
    log_changes and keyitems link by it alike."""

    def __init__(self):
        self.open: dict | None = None  # the start row of the event under way
        self.last: tuple[dict, int] | None = None  # (start row, ts of its last packet)

    def see(self, ts: int, start: dict | None = None) -> dict | None:
        """An event packet at ts, which begins start if given; returns the event it belongs to."""
        if start is not None:
            self.open = start
        if self.open is not None:
            self.last = (self.open, ts)
        return self.open

    def end(self) -> None:
        """The event under way is over: a release or a zone-in. It still links changes for LINK_MS."""
        self.open = None

    def at(self, ts: int) -> dict | None:
        if self.open is not None:
            return self.open
        if self.last and ts - self.last[1] <= LINK_MS:
            return self.last[0]
        return None

    def follow(self, key: tuple[int, int], p, f) -> None:
        """Follow an event packet or a zone-in, for a unit that links its rows to the event's start packet: a
        zone-in ends the event under way, and starts one when it plays a cutscene."""
        if key == (0, 0x00A):
            self.end()
            if f("EventNum"):
                self.see(p.ts_ms, {"idx": p.idx, "event_id": f("EventPara")})
            return
        self.see(p.ts_ms, {"idx": p.idx, "event_id": f("EventPara")} if KINDS[key] == "start" else None)
        if KINDS[key] == "release":
            self.end()
