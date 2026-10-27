## Transport Layer & Packet Framing Mechanism

**Transport Protocol:** TCP

**Serialization Format:** Structured JSON (or delimited text / binary - student choice)

**Framing Rule Requirement:** TCP is a continuous byte-stream protocol without built-in message boundaries. Multiple messages sent back-to-back may arrive in a single recv() chunk (coalescing), or a single message may be split across multiple chunks (fragmentation). Your protocol blueprint must explicitly define a deterministic framing rule to delimit message boundaries on the wire.


**Framing Rule:** Message fields are separated by ASCII Hex `1E`, and every complete message is terminated with ASCII Hex `1F`. Any printable ASCII character can be used within a field.<br>
<sub>I've borrowed some of this from a joke protocol I made for a CSU DevNet project recently, called [TDLP](https://app.notion.com/p/TDLP-ToDo-List-Protocol-3f8c26680a4580d2b7a1d6146a9eae2b) (the basic format is [TLON](https://app.notion.com/p/TLON-3f8c26680a4580df8807f80b26a27c53))<sub>

### Schema Specification:

#### Header (6 bytes, 1 field):
- Action (1 byte)
	- Action this message is communicating
- Game ID + Player ID (1 byte)
	- A combo game-player id, where the first 6 bits are the game id, and the last 2 bits represents the player id. 
		- For the server, the player id is 0 (`b00`). 
		- Player id 3 (`b11`) can be used as a "spectator" id, allowing additional clients to view the state of the game without being able to modify it.
- Timestamp (Unsigned 4 byte int)
	- Time in seconds from the Unix Epoch

#### Payload Styles (Varies by action):
- Guess
	- Single, 1 byte field containing coordinates
	- `GUESS` action
- Start
	- 1 field, assigned Player_ID
	- `START` action
- Setup
	- 1 field per ship (default 5 ships)
		- Each field contains a full ship definition as described at the bottom of this page
	- `SETUP` action
- Turn End
	- 2 fields
		- 1: 2 bytes, indicating HIT or MISS and coordinates
			- 1: `b00000000` for MISS or `b00000001` for HIT
			- 2: Coordinates
		- 2: Player_ID of which player's turn it is now
	- `TURN_END` action
- Game End
	- 1 field for winning Player_ID, 1 field per winning player's ship, then repeated for the loosing player
		- 1: Winner's Player_ID
		- 2-6: Winner's ships, as a full ship definition (assuming default 5 ships)
		- 7: Looser's Player_ID
		- 8-12: Looser's ships, as a full ship definition (assuming default 5 ships)
- No Payload
	- `CONNECT`, `DISCONNECT` actions

#### Actions
| Action | Byte Representation | Direction | Purpose |
| --- | --- | --- | --- |
| CONNECT | `b00000001` | Client -> Server | Request to join game |
| DISCONNECT | `b00000010` | Client -> Server | Intentional disconnect |
| START | `b00000011` | Server -> Client | Game starting, server assigns player numbers and awaits client setup |
| SETUP | `b00000100` | Client -> Server | Client tells server of decided ship placements |
| TURN_END | `b00000101` | Server -> Clients | Server notifies clients of a HIT or MISS and coordinates, and specifies which player's turn it is now |
| GUESS | `b00000111` | Client -> Server | Client's guess for enemy ship position |
| END | `b00001000` | Server -> Clients | Server broadcasts game outcome |
| ERROR | `b00001001` | Server -> Client | Invalid move or malformed message |

**Coordinates:** A single byte, with bits 1-4 representing X and bits 5-8 representing Y. A classic battleship game uses a 10x10 board, and this will allow up to a 16x16 board. <br>
**Ship IDs:** A single byte, with bit 1-2 representing Player ID, and bits 3-5 representing the ship type. Padded to 1 full byte to suit TCP.
- A full ship definition can be represented in 3 bytes:
	- 1: Ship ID
	- 2: Start Coordinates
	- 3: End Coordiantes