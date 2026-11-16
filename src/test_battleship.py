import contextlib
import io
import socket
import threading
import unittest
from unittest.mock import patch

from src import client
from src.game import Game, State, fleet_cells
from src.protocol import Action, Decoder, Message, ProtocolError, coordinate, encode
from src.server import Server


def fleet(player):
    return tuple(
        bytes([kind << 2 | player, (kind - 1) << 4, (kind - 1) << 4 | (length - 1)])
        for kind, length in enumerate((5, 4, 3, 3, 2), 1)
    )


class ProtocolTests(unittest.TestCase):
    def test_all_byte_values_fragmented_and_coalesced(self):
        message = Message(Action.SETUP, 7, 2, (bytes(range(256)), b""), 0x1B1E1F00)
        wire = encode(message)
        decoder = Decoder()
        result = []
        for value in wire:
            result.extend(decoder.feed(bytes([value])))
        self.assertEqual(result, [message])
        self.assertEqual(Decoder().feed(wire * 3), [message] * 3)

    def test_bad_framing(self):
        for wire in (b"bad\x1f", b"\x1b\x00", b"x" * 4097):
            with self.assertRaises(ProtocolError):
                Decoder().feed(wire)

    def test_coordinate(self):
        self.assertEqual(coordinate("J10"), 0x99)
        for value in ("K1", "A0", "A11", "bad"):
            with self.assertRaises(ValueError):
                coordinate(value)


class GameTests(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.game.join(1)
        self.game.join(2)

    def setup_fleets(self):
        for player in (2, 1):
            self.game.handle(player, Message(Action.SETUP, 1, player, fleet(player)))

    def test_validation_and_first_ready(self):
        bad = list(fleet(1))
        bad[1] = bytes([9, 0, 3])
        with self.assertRaises(ValueError):
            fleet_cells(bad, 1)
        self.setup_fleets()
        self.assertEqual(self.game.turn, 2)
        with self.assertRaises(ValueError):
            self.game.handle(1, Message(Action.GUESS, 1, 1, (b"\x00",)))
        self.game.handle(2, Message(Action.GUESS, 1, 2, (b"\x99",)))
        self.game.handle(1, Message(Action.GUESS, 1, 1, (b"\x99",)))
        with self.assertRaises(ValueError):
            self.game.handle(2, Message(Action.GUESS, 1, 2, (b"\x99",)))
        self.assertEqual(self.game.state, State.PLAYER_TURN)
        self.assertEqual(self.game.turn, 2)

    def test_victory_reveals_fleets(self):
        self.setup_fleets()
        targets = [cell for ship in self.game.ships[1].values() for cell in ship]
        for index, target in enumerate(targets):
            replies = self.game.handle(
                2, Message(Action.GUESS, 1, 2, (bytes([target]),))
            )
            if index < len(targets) - 1:
                self.game.handle(
                    1,
                    Message(
                        Action.GUESS,
                        1,
                        1,
                        (bytes([0x50 + (index // 10) * 16 + index % 10]),),
                    ),
                )
        self.assertEqual(self.game.state, State.GAME_OVER)
        self.assertEqual(replies[-1][1].action, Action.END)
        self.assertEqual(
            replies[-1][1].fields, (b"\x02", *fleet(2), b"\x01", *fleet(1))
        )


class NetworkTests(unittest.TestCase):
    def test_two_connections_disconnect_and_reuse(self):
        server = Server()
        threads, peers = [], []
        try:
            for player in (1, 2):
                peer, connection = socket.socketpair()
                peer.settimeout(3)
                peers.append(peer)
                thread = threading.Thread(
                    target=server.serve_client, args=(connection, ("local", player))
                )
                thread.start()
                threads.append(thread)
                peer.sendall(encode(Message(Action.CONNECT)))
                if player == 1:
                    # Synchronize registration before assigning the next player.
                    with server.lock:
                        pass
            decoders = [Decoder(), Decoder()]

            def receive(index):
                messages = []
                while not messages:
                    messages = decoders[index].feed(peers[index].recv(4096))
                return messages

            starts = [receive(0)[0], receive(1)[0]]
            for index, start in enumerate(starts):
                player = start.fields[0][0]
                peers[index].sendall(
                    encode(Message(Action.SETUP, start.game, player, fleet(player)))
                )
            initial = [receive(0)[0], receive(1)[0]]
            active = initial[0].fields[1][0]
            for turn in range(4):
                index = next(
                    i for i, m in enumerate(starts) if m.fields[0][0] == active
                )
                peers[index].sendall(
                    encode(
                        Message(
                            Action.GUESS,
                            starts[index].game,
                            active,
                            (bytes([0x90 + turn]),),
                        )
                    )
                )
                updates = [receive(0)[0], receive(1)[0]]
                self.assertEqual(updates[0], updates[1])
                active = updates[0].fields[1][0]
            peers[0].close()
            self.assertEqual(receive(1)[0].action, Action.ERROR)
            for thread in threads:
                thread.join(3)
                self.assertFalse(thread.is_alive())
            self.assertEqual(server.game.state, State.WAITING_FOR_PLAYERS)
            self.assertFalse(server.clients)
            # A fresh pair must receive a new game, not stale state or identities.
            for peer in peers:
                peer.close()
            for player in (1, 2):
                peer, connection = socket.socketpair()
                peer.settimeout(3)
                peers[player - 1] = peer
                thread = threading.Thread(
                    target=server.serve_client, args=(connection, ("new", player))
                )
                thread.start()
                threads.append(thread)
                peer.sendall(encode(Message(Action.CONNECT)))
            decoders = [Decoder(), Decoder()]
            for index in (0, 1):
                start = receive(index)[0]
                self.assertEqual(start.action, Action.START)
                self.assertEqual(start.game, 2)
        finally:
            for peer in peers:
                peer.close()
            for thread in threads:
                thread.join(3)

    def test_dns_failure_is_friendly(self):
        output = io.StringIO()
        with (
            patch("sys.argv", ["client.py", "-i", "bad.invalid", "-p", "8080"]),
            patch("socket.gethostbyname", side_effect=socket.gaierror("DNS failed")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(client.main(), 1)
        self.assertIn("ip dns server", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
