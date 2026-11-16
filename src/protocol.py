"""Battleship binary messages, with incremental TCP framing."""

from dataclasses import dataclass
from enum import IntEnum
import struct
import time


class Action(IntEnum):
    CONNECT = 1
    DISCONNECT = 2
    START = 3
    SETUP = 4
    TURN_END = 5
    GUESS = 7
    END = 8
    ERROR = 9


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Message:
    action: Action
    game: int = 0
    player: int = 0
    fields: tuple = ()
    timestamp: int = 0


def escape(field):
    output = bytearray()
    for value in field:
        if value in (0x1B, 0x1E, 0x1F):
            output.extend((0x1B, value ^ 0x20))
        else:
            output.append(value)
    return bytes(output)


def encode(message):
    if not 0 <= message.game <= 63 or not 0 <= message.player <= 3:
        raise ProtocolError("Invalid game or player ID")
    header = struct.pack("!BBI", message.action,
                         message.game << 2 | message.player,
                         message.timestamp or int(time.time()))
    return b"\x1e".join(escape(f) for f in (header, *message.fields)) + b"\x1f"


class Decoder:
    """Retain partial fields across recv calls; bound unfinished messages."""

    def __init__(self):
        self.fields = []
        self.field = bytearray()
        self.escaped = False
        self.size = 0

    def feed(self, data):
        messages = []
        for value in data:
            self.size += 1
            if self.size > 4096:
                raise ProtocolError("Message exceeds 4096 bytes")
            if self.escaped:
                if value not in (0x3B, 0x3E, 0x3F):
                    raise ProtocolError("Invalid byte escape")
                self.field.append(value ^ 0x20)
                self.escaped = False
            elif value == 0x1B:
                self.escaped = True
            elif value in (0x1E, 0x1F):
                self.fields.append(bytes(self.field))
                self.field.clear()
                if value == 0x1F:
                    if len(self.fields[0]) != 6:
                        raise ProtocolError("Header must contain six bytes")
                    action, identity, timestamp = struct.unpack("!BBI", self.fields[0])
                    try:
                        action = Action(action)
                    except ValueError as exc:
                        raise ProtocolError("Unknown action") from exc
                    messages.append(Message(action, identity >> 2, identity & 3,
                                            tuple(self.fields[1:]), timestamp))
                    self.fields.clear()
                    self.size = 0
            else:
                self.field.append(value)
        return messages


def coordinate(text):
    text = text.strip().upper()
    if len(text) < 2 or text[0] not in "ABCDEFGHIJ":
        raise ValueError("Use a coordinate from A1 to J10")
    try:
        row = int(text[1:]) - 1
    except ValueError as exc:
        raise ValueError("Use a coordinate from A1 to J10") from exc
    if not 0 <= row < 10:
        raise ValueError("Use a coordinate from A1 to J10")
    return row << 4 | (ord(text[0]) - ord("A"))


def valid_coordinate(value):
    return value & 15 < 10 and value >> 4 < 10


def label(value):
    return f"{chr(65 + (value & 15))}{(value >> 4) + 1}"


def port(text):
    import argparse
    try:
        value = int(text)
        if 1 <= value <= 65535:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Port must be between 1 and 65535")
