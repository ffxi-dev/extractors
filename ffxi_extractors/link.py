"""The packets an event is made of, which events, obtained, and key items read to tell the event a change
follows; rust/extractors/link keeps the event under way."""

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
