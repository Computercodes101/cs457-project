from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading


ROOT = Path(__file__).resolve().parent


class Session:
    def __init__(self, name, script, *args):
        self.name = name
        self.lines = queue.Queue()
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / script), *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.process.stdout:
            self.lines.put(line.rstrip())
        self.lines.put(None)

    def wait_for(self, text):
        while True:
            line = self.lines.get(timeout=10)
            if line is None:
                raise RuntimeError(f"{self.name} exited before {text!r}")
            print(f"[{self.name}] {line}", flush=True)
            if text in line:
                return line

    def send(self, text):
        print(f"[{self.name} INPUT] {text}", flush=True)
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def drain(self):
        while True:
            line = self.lines.get(timeout=10)
            if line is None:
                return
            print(f"[{self.name}] {line}", flush=True)


def main():
    sessions = []
    # Select a free local port; the production server still binds to 0.0.0.0.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        listening_port = str(probe.getsockname()[1])
    try:
        server = Session("SERVER", "server.py", "-p", listening_port)
        sessions.append(server)
        server.wait_for("Listening on")
        players = []
        for number in (1, 2):
            player = Session(
                f"CLIENT {number}", "client.py", "-i", "localhost", "-p", listening_port
            )
            sessions.append(player)
            players.append(player)
            player.wait_for("Connected.")
        assigned = {}
        for player in players:
            assignment = player.wait_for("You are Player")
            number = int(assignment.split("You are Player ")[1].split(".")[0])
            assigned[number] = player
            player.wait_for("Ship 1")
        players = [assigned[1], assigned[2]]
        for player in players:
            for index, placement in enumerate(
                ("A1 E1", "A2 D2", "A3 C3", "A4 C4", "A5 B5")
            ):
                player.send(placement)
                player.wait_for(
                    f"Ship {index + 2}" if index < 4 else "Fleet submitted."
                )
        players[0].wait_for("Your Turn")
        players[1].wait_for("Waiting for Player 1")
        for turn, guess in enumerate(("A1", "J10", "J10", "A1")):
            active = turn % 2
            players[active].send(guess)
            players[active].wait_for(f"Waiting for Player {2 - active}")
            players[1 - active].wait_for("Your Turn")
        print("[DEMO] Four turns completed; both clients received every result.")
        players[0].send("quit")
        players[0].process.wait(timeout=10)
        players[1].wait_for("Opponent disconnected")
        players[1].process.wait(timeout=10)
        for player in players:
            player.drain()
        server.wait_for("PLAYER_TURN -> CLEANUP")
        server.wait_for("INIT -> WAITING_FOR_PLAYERS")
        print("[DEMO] Disconnect cleanup verified; server ready for another game.")
    finally:
        for session in reversed(sessions):
            if session.process.poll() is None:
                session.process.terminate()
            session.process.wait(timeout=10)


if __name__ == "__main__":
    main()
