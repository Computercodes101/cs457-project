import argparse
import socket
import threading

from src.game import Game, State
from src.protocol import Action, Decoder, ProtocolError, encode, port


class Server:
    def __init__(self):
        self.lock = threading.RLock()
        self.clients = {}
        self.game = Game()

    def send(self, connection, message):
        # Bounded sends prevent a stalled peer from holding the game lock forever.
        connection.sendall(encode(message))

    def dispatch(self, replies):
        for target, message in replies:
            for player, connection in list(self.clients.items()):
                if target in (0, player):
                    try:
                        self.send(connection, message)
                    except OSError:
                        connection.close()

    def cleanup(self):
        self.game.transition(State.CLEANUP)
        for connection in self.clients.values():
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        self.clients.clear()
        self.game = Game(self.game.id % 63 + 1)

    def serve_client(self, connection, address):
        decoder = Decoder()
        player = None
        session = None
        connection.settimeout(1)
        print(f"[CONNECT] {address}", flush=True)
        try:
            while True:
                try:
                    data = connection.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                for message in decoder.feed(data):
                    with self.lock:
                        if player is None:
                            if (
                                message.action != Action.CONNECT
                                or message.fields
                                or message.player
                                or message.game
                            ):
                                raise ProtocolError(
                                    "First message must be CONNECT with zero IDs"
                                )
                            if len(self.clients) >= 2:
                                self.send(
                                    connection,
                                    self.game.message(
                                        Action.ERROR,
                                        (b"\x01", b"Server full; try again later"),
                                    ),
                                )
                                return
                            player = next(p for p in (1, 2) if p not in self.clients)
                            session = self.game
                            self.clients[player] = connection
                            self.dispatch(self.game.join(player))
                        elif session is not self.game:
                            return
                        elif message.action == Action.DISCONNECT:
                            if (
                                message.fields
                                or message.game != session.id
                                or message.player != player
                            ):
                                raise ProtocolError("Invalid DISCONNECT")
                            return
                        else:
                            try:
                                self.dispatch(self.game.handle(player, message))
                            except ValueError as exc:
                                self.send(
                                    connection,
                                    self.game.message(
                                        Action.ERROR,
                                        (b"\x02", str(exc).encode("ascii")),
                                    ),
                                )
                            if self.game.state == State.GAME_OVER:
                                self.cleanup()
                                return
        except ProtocolError as exc:
            with self.lock:
                try:
                    self.send(
                        connection,
                        self.game.message(
                            Action.ERROR, (b"\x03", str(exc).encode("ascii"))
                        ),
                    )
                except OSError:
                    pass
        except OSError:
            pass
        finally:
            with self.lock:
                if session is self.game and self.clients.get(player) is connection:
                    del self.clients[player]
                    if self.game.state == State.WAITING_FOR_PLAYERS:
                        self.game.players.discard(player)
                    else:
                        self.dispatch(
                            [
                                (
                                    0,
                                    self.game.message(
                                        Action.ERROR,
                                        (
                                            b"\x04",
                                            b"Opponent disconnected; game aborted",
                                        ),
                                    ),
                                )
                            ]
                        )
                        self.cleanup()
            connection.close()

    def run(self, listening_port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", listening_port))
            listener.listen()
            print(f"Listening on 0.0.0.0:{listener.getsockname()[1]}", flush=True)
            try:
                while True:
                    connection, address = listener.accept()
                    threading.Thread(
                        target=self.serve_client,
                        args=(connection, address),
                        daemon=True,
                    ).start()
            finally:
                with self.lock:
                    self.cleanup()


def main():
    parser = argparse.ArgumentParser(description="Host a two-player Battleship game")
    parser.add_argument("-p", required=True, type=port, help="Listening TCP port")
    args = parser.parse_args()
    try:
        Server().run(args.p)
    except KeyboardInterrupt:
        print("\nServer stopped.")
    except OSError as exc:
        print(f"[ERROR] Server network error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
