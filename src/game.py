from enum import Enum

from src.protocol import Action, Message, valid_coordinate

FLEET = {1: 5, 2: 4, 3: 3, 4: 3, 5: 2}


class State(Enum):
    INIT = "INIT"
    WAITING_FOR_PLAYERS = "WAITING_FOR_PLAYERS"
    GAME_START = "GAME_START"
    WAITING_FOR_SETUP = "WAITING_FOR_SETUP"
    PLAYER_TURN = "PLAYER_TURN"
    EVALUATE_GUESS = "EVALUATE_GUESS"
    GAME_OVER = "GAME_OVER"
    CLEANUP = "CLEANUP"


def fleet_cells(fields, player):
    if len(fields) != 5:
        raise ValueError("Provide exactly five ships")
    ships = {}
    occupied = set()
    for field in fields:
        if len(field) != 3:
            raise ValueError("Each ship requires ID, start, and end bytes")
        identity, start, end = field
        kind = identity >> 2
        if identity & 3 != player or kind not in FLEET or kind in ships:
            raise ValueError("Invalid or duplicate ship ID")
        if not valid_coordinate(start) or not valid_coordinate(end):
            raise ValueError("Ships must be within A1-J10")
        x1, y1, x2, y2 = start & 15, start >> 4, end & 15, end >> 4
        if x1 != x2 and y1 != y2:
            raise ValueError("Ships must be horizontal or vertical")
        cells = {
            y << 4 | x
            for y in range(min(y1, y2), max(y1, y2) + 1)
            for x in range(min(x1, x2), max(x1, x2) + 1)
        }
        if len(cells) != FLEET[kind] or occupied & cells:
            raise ValueError("Incorrect ship length or overlapping ships")
        occupied.update(cells)
        ships[kind] = {cell: False for cell in cells}
    return ships


class Game:
    """Caller holds the server lock for every state change and response."""

    def __init__(self, game_id=1):
        self.id = game_id
        self.state = State.INIT
        self.players = set()
        self.ships = {}
        self.placements = {}
        self.guesses = {1: set(), 2: set()}
        self.first_ready = None
        self.turn = None
        self.transition(State.WAITING_FOR_PLAYERS)

    def transition(self, state):
        print(f"[FSM] {self.state.value} -> {state.value}", flush=True)
        self.state = state

    def message(self, action, fields=()):
        return Message(action, self.id, 0, tuple(fields))

    def join(self, player):
        self.players.add(player)
        if len(self.players) != 2:
            return []
        self.transition(State.GAME_START)
        replies = [
            (p, self.message(Action.START, (bytes([p]),))) for p in sorted(self.players)
        ]
        self.transition(State.WAITING_FOR_SETUP)
        return replies

    def handle(self, player, message):
        if message.game != self.id or message.player != player:
            raise ValueError("Message identity does not match this connection")
        if message.action == Action.SETUP and self.state == State.WAITING_FOR_SETUP:
            if player in self.ships:
                raise ValueError("Fleet already submitted")
            ships = fleet_cells(message.fields, player)
            self.ships[player] = ships
            self.placements[player] = message.fields
            if self.first_ready is None:
                self.first_ready = player
            if len(self.ships) == 2:
                self.turn = self.first_ready
                self.transition(State.PLAYER_TURN)
                # Empty result denotes the initial turn, before any shot.
                return [(0, self.message(Action.TURN_END, (b"", bytes([self.turn]))))]
            return []
        if message.action != Action.GUESS or self.state != State.PLAYER_TURN:
            raise ValueError("Action is not allowed in the current state")
        if player != self.turn:
            raise ValueError("It is not your turn")
        self.transition(State.EVALUATE_GUESS)
        if (
            len(message.fields) != 1
            or len(message.fields[0]) != 1
            or not valid_coordinate(message.fields[0][0])
        ):
            self.transition(State.PLAYER_TURN)
            raise ValueError("Guess must be one coordinate within A1-J10")
        cell = message.fields[0][0]
        if cell in self.guesses[player]:
            self.transition(State.PLAYER_TURN)
            raise ValueError("You already guessed that coordinate")
        self.guesses[player].add(cell)
        opponent = 3 - player
        hit = False
        for ship in self.ships[opponent].values():
            if cell in ship:
                ship[cell] = True
                hit = True
        self.turn = opponent
        replies = [
            (0, self.message(Action.TURN_END, (bytes([hit, cell]), bytes([self.turn]))))
        ]
        if all(hit for ship in self.ships[opponent].values() for hit in ship.values()):
            self.transition(State.GAME_OVER)
            fields = (
                bytes([player]),
                *self.placements[player],
                bytes([opponent]),
                *self.placements[opponent],
            )
            replies.append((0, self.message(Action.END, fields)))
        else:
            self.transition(State.PLAYER_TURN)
        return replies
