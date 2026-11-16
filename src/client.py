import argparse
import queue
import socket
import threading

from src.game import FLEET, fleet_cells
from src.protocol import (
    Action,
    Decoder,
    Message,
    ProtocolError,
    coordinate,
    encode,
    label,
    port,
)


def render(ships, incoming, outgoing):
    occupied = {cell for ship in ships.values() for cell in ship}
    print("\n       YOUR FLEET                         YOUR SHOTS")
    print("    A B C D E F G H I J               A B C D E F G H I J")
    for row in range(10):
        own, shots = [], []
        for column in range(10):
            cell = row << 4 | column
            own.append(incoming.get(cell, "S" if cell in occupied else "."))
            shots.append(outgoing.get(cell, "."))
        print(f"{row + 1:2}  {' '.join(own)}          {row + 1:2}  {' '.join(shots)}")
    print("S = ship, X = hit, o = miss")
    hits = sum(value == "X" for value in outgoing.values())
    damage = sum(value == "X" for value in incoming.values())
    print(f"Score: hits {hits}/17 | Your surviving cells: {17 - damage}/17")


class Client:
    def __init__(self, connection):
        self.connection = connection
        self.events = queue.Queue()
        self.game = 0
        self.player = 0
        self.phase = "waiting"
        self.placements = []
        self.ships = {}
        self.incoming = {}
        self.outgoing = {}

    def send(self, action, fields=()):
        self.connection.sendall(
            encode(Message(action, self.game, self.player, tuple(fields)))
        )

    def receive(self):
        decoder = Decoder()
        try:
            while True:
                data = self.connection.recv(4096)
                if not data:
                    break
                for message in decoder.feed(data):
                    self.events.put(("message", message))
        except (OSError, ProtocolError) as exc:
            self.events.put(("network_error", str(exc)))
        finally:
            self.events.put(("closed", None))

    def read_input(self):
        # Keep socket notifications responsive while the user is at a prompt.
        while True:
            try:
                line = input()
            except EOFError:
                self.events.put(("eof", None))
                return
            self.events.put(("input", line))

    def prompt_setup(self):
        kind = len(self.placements) + 1
        print(
            f"Ship {kind} (length {FLEET[kind]}): enter start end (e.g. A1 E1):",
            flush=True,
        )

    def handle_input(self, text):
        if text.strip().lower() in ("quit", "exit"):
            self.send(Action.DISCONNECT)
            return False
        try:
            if self.phase == "setup":
                parts = text.split()
                if len(parts) != 2:
                    raise ValueError("Enter two coordinates separated by a space")
                kind = len(self.placements) + 1
                field = bytes(
                    [
                        kind << 2 | self.player,
                        coordinate(parts[0]),
                        coordinate(parts[1]),
                    ]
                )
                # Validate incrementally by checking geometry and existing cells.
                start, end = field[1:]
                x1, y1, x2, y2 = start & 15, start >> 4, end & 15, end >> 4
                cells = {
                    y << 4 | x
                    for y in range(min(y1, y2), max(y1, y2) + 1)
                    for x in range(min(x1, x2), max(x1, x2) + 1)
                }
                occupied = {cell for ship in self.ships.values() for cell in ship}
                if (
                    (x1 != x2 and y1 != y2)
                    or len(cells) != FLEET[kind]
                    or cells & occupied
                ):
                    raise ValueError(
                        "Ship must be straight, the correct length, and not overlap"
                    )
                self.placements.append(field)
                self.ships[kind] = {cell: False for cell in cells}
                if len(self.placements) == 5:
                    fleet_cells(self.placements, self.player)
                    self.send(Action.SETUP, self.placements)
                    self.phase = "ready"
                    render(self.ships, self.incoming, self.outgoing)
                    print("Fleet submitted. Waiting for the other player's setup...")
                else:
                    self.prompt_setup()
            elif self.phase == "turn":
                cell = coordinate(text)
                if cell in self.outgoing:
                    raise ValueError("You already guessed that coordinate")
                self.send(Action.GUESS, (bytes([cell]),))
                self.phase = "pending"
            else:
                print("Waiting for the server or other player. Type quit to leave.")
        except ValueError as exc:
            print(f"[ERROR] {exc}")
            if self.phase == "setup":
                self.prompt_setup()
            elif self.phase == "turn":
                print("Your Turn: enter A1-J10:", flush=True)
        return True

    def handle_message(self, message):
        fields = message.fields
        if message.action == Action.START:
            if len(fields) != 1 or fields[0] not in (b"\x01", b"\x02"):
                raise ProtocolError("Invalid START")
            self.game, self.player = message.game, fields[0][0]
            self.phase = "setup"
            print(
                f"Game {self.game}: You are Player {self.player}. Type quit to leave."
            )
            self.prompt_setup()
        elif message.action == Action.TURN_END:
            if (
                len(fields) != 2
                or fields[1] not in (b"\x01", b"\x02")
                or len(fields[0]) not in (0, 2)
            ):
                raise ProtocolError("Invalid TURN_END")
            next_player = fields[1][0]
            if fields[0]:
                hit, cell = fields[0]
                shooter = 3 - next_player
                board = self.outgoing if shooter == self.player else self.incoming
                board[cell] = "X" if hit else "o"
                print(
                    f"Player {shooter} fired at {label(cell)}: {'HIT' if hit else 'MISS'}"
                )
            render(self.ships, self.incoming, self.outgoing)
            self.phase = "turn" if next_player == self.player else "waiting"
            print(
                "Your Turn: enter A1-J10:"
                if self.phase == "turn"
                else f"Waiting for Player {next_player}...",
                flush=True,
            )
        elif message.action == Action.ERROR:
            if len(fields) != 2 or len(fields[0]) != 1:
                raise ProtocolError("Invalid ERROR")
            print(f"[ERROR] {fields[1].decode('ascii', errors='replace')}")
            if fields[0] in (b"\x01", b"\x03", b"\x04"):
                return False
            if self.phase == "ready":
                self.placements.clear()
                self.ships.clear()
                self.phase = "setup"
                self.prompt_setup()
            elif self.phase == "pending":
                self.phase = "turn"
                print("Your Turn: enter A1-J10:", flush=True)
        elif message.action == Action.END:
            if len(fields) != 12 or fields[0] not in (b"\x01", b"\x02"):
                raise ProtocolError("Invalid END")
            winner = fields[0][0]
            outcome = "You won!" if winner == self.player else "You lost."
            print(f"Game over. Player {winner} wins! {outcome}")
            print("Final fleets:")
            for offset in (0, 6):
                print(f"Player {fields[offset][0]}:")
                for ship in fields[offset + 1 : offset + 6]:
                    if len(ship) != 3:
                        raise ProtocolError("Invalid final ship")
                    print(f"  Ship {ship[0] >> 2}: {label(ship[1])}-{label(ship[2])}")
            return False
        else:
            raise ProtocolError("Unexpected server action")
        return True

    def run(self):
        self.send(Action.CONNECT)
        print("Connected. Waiting for Player 2...", flush=True)
        threading.Thread(target=self.receive, daemon=True).start()
        threading.Thread(target=self.read_input, daemon=True).start()
        while True:
            event, value = self.events.get()
            if event == "message":
                if not self.handle_message(value):
                    return 0
            elif event == "input":
                if not self.handle_input(value):
                    return 0
            elif event == "eof":
                self.send(Action.DISCONNECT)
                return 0
            elif event == "network_error":
                print(f"[ERROR] Connection failed: {value}")
                return 1
            elif event == "closed":
                print("Server closed the connection.")
                return 1


def main():
    parser = argparse.ArgumentParser(description="Play network Battleship")
    parser.add_argument(
        "-i", dest="hostname", required=True, help="Server DNS hostname"
    )
    parser.add_argument("-p", required=True, type=port, help="Server TCP port")
    args = parser.parse_args()
    try:
        server_ip = socket.gethostbyname(args.hostname)
    except socket.gaierror:
        print(f"[ERROR] Unable to resolve DNS hostname '{args.hostname}'.")
        print(
            "Please check your Cisco router DNS configuration ('ip dns server' / 'ip host') "
            "or verify domain spelling."
        )
        return 1
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(10)
            connection.connect((server_ip, args.p))
            connection.settimeout(None)
            return Client(connection).run()
    except KeyboardInterrupt:
        print("\nDisconnected.")
        return 0
    except (OSError, ProtocolError) as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
