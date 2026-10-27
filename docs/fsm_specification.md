
stateDiagram-v2
    direction TB

    [*] --> INIT

    INIT --> WAITING_FOR_PLAYERS: Server started and listening

    WAITING_FOR_PLAYERS --> WAITING_FOR_PLAYERS: CONNECT / Waiting for second player
    WAITING_FOR_PLAYERS --> GAME_START: 2 clients connected

    GAME_START --> WAITING_FOR_SETUP: Broadcast START / Assign player numbers

    WAITING_FOR_SETUP --> WAITING_FOR_SETUP: SETUP / First player ready
    WAITING_FOR_SETUP --> PLAYER_TURN: Both players submitted valid SETUP

    WAITING_FOR_SETUP --> WAITING_FOR_SETUP: Invalid SETUP / Send ERROR

    PLAYER_TURN --> EVALUATE_GUESS: Active player sends GUESS
    PLAYER_TURN --> PLAYER_TURN: Invalid action / Send ERROR

    EVALUATE_GUESS --> PLAYER_TURN: HIT or MISS / Broadcast TURN_END
    EVALUATE_GUESS --> PLAYER_TURN: Invalid GUESS / Send ERROR
    EVALUATE_GUESS --> GAME_OVER: All enemy ships sunk

    GAME_OVER --> CLEANUP: Broadcast END / Final results
    CLEANUP --> WAITING_FOR_PLAYERS: Reset game state

    WAITING_FOR_PLAYERS --> WAITING_FOR_PLAYERS: DISCONNECT / Remove player
    WAITING_FOR_SETUP --> CLEANUP: DISCONNECT / Abort game
    PLAYER_TURN --> CLEANUP: DISCONNECT / Abort game
    EVALUATE_GUESS --> CLEANUP: DISCONNECT / Abort game
