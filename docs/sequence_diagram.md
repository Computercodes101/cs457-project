sequenceDiagram
    autonumber
    actor C1 as Client 1
    participant S as Game Server
    actor C2 as Client 2

    Note over S: Server listening for connections

    par Player Connections
        C1->>S: CONNECT (0x01)
    and
        C2->>S: CONNECT (0x01)
    end

    Note over S: Lock game state<br/>Register players<br/>Unlock game state

    par Start Game
        S-->>C1: START (0x03, Player 1)
    and
        S-->>C2: START (0x03, Player 2)
    end

    Note over C1,C2: Players independently place their ships

    par Ship Setup
        C1->>S: SETUP (0x04, Ship Placements)
    and
        C2->>S: SETUP (0x04, Ship Placements)
    end

    Note over S: Validate ship placements<br/>Lock and update readiness<br/>Unlock game state

    opt Invalid Ship Placement
        S-->>C1: ERROR (0x09, Invalid Setup)
        C1->>S: SETUP (0x04, Corrected Placements)
    end

    Note over S: Both players ready<br/>Initialize active turn

    loop Until Victory or Disconnection
        Note over C1,C2: Active player submits a guess

        alt Player 1 Turn
            C1->>S: GUESS (0x07, Coordinates)
        else Player 2 Turn
            C2->>S: GUESS (0x07, Coordinates)
        end

        Note over S: Acquire game state lock<br/>Validate turn and coordinates

        alt Invalid Guess
            S-->>C1: ERROR (0x09, If Client 1 submitted)
            S-->>C2: ERROR (0x09, If Client 2 submitted)
            Note over S: No state change
        else Valid Guess
            Note over S: Apply HIT or MISS<br/>Check for victory

            alt Game Continues
                Note over S: Update active player
                par Broadcast Turn Result
                    S-->>C1: TURN_END (0x05, Result, Coordinates, Next Turn)
                and
                    S-->>C2: TURN_END (0x05, Result, Coordinates, Next Turn)
                end
            else Victory
                par Broadcast Outcome
                    S-->>C1: END (0x08, Game Outcome)
                and
                    S-->>C2: END (0x08, Game Outcome)
                end
            end
        end

        Note over S: Release game state lock
    end

    opt Client Disconnects
        C1->>S: DISCONNECT (0x02)
        Note over S: Safely terminate or update game session
    end