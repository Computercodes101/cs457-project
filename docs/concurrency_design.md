## Server Concurrency Architecture 

### Server Concurrency Model

The server will use multi-threading with a dedicated thread per client. The main thread will only be used to accept client connections. Shared memory structures will be used between threads for each game that are locked to prevent race conditions when modified.

### Sequence Diagram

Due to the size of the sequence diagram, it has been placed in [sequence_diagram.md](sequence_diagram.md).

### Round State

Battleship doesn't have a traditional leaderboard or score, it lasts until a player is eliminated. Each player will have a dictionary with each shipid as a key, with another dictionary containing each coordinate the ship takes up as keys and a boolean for if it has been hit as a value.

Example structure:
```python
player_1_state = {
	1: {
		(0, 0): False, 
		(0, 1): False
	}
}
```
(Ships are classified by a number)

Once all of a player's ship's coordinates have been hit, the player has lost and their opponent has won. The `END` message will be broadcast containing each player's ship positions as specified in [protocol_blueprint.md](protocol_blueprint.md).

Separately, the game will track all of each player's guesses and which player's turn it is, only accepting actions if it is that player's turn.