# sse-cursor-reconnect Specification

## Purpose
TBD - created by archiving change sap-nexus-incremental-sse-reconnect. Update Purpose after archive.
## Requirements
### Requirement: Incremental SSE delivery

The system SHALL publish each AgentRunEvent to the SSE stream incrementally as it is produced, not buffered until the Agent subprocess completes. Each published event SHALL carry its `sequence` field so the client can track the last received event.

#### Scenario: events stream incrementally

- **WHEN** an agent run emits a `run_started` event before the run reaches `run_completed`
- **THEN** the client connected to the SSE stream SHALL receive the `run_started` event immediately
- **AND** the client SHALL NOT have to wait until `run_completed` to receive any event

### Requirement: Event cursor for reconnect

The system SHALL support a reconnect cursor based on the event `sequence`. A client reconnecting with a cursor SHALL receive all events whose sequence is strictly greater than the cursor value.

#### Scenario: reconnect resumes from cursor

- **WHEN** a client disconnects after receiving an event with sequence N and reconnects with `cursor=N`
- **THEN** the server SHALL resume delivery starting from the event with sequence N+1
- **AND** the client SHALL receive every event it missed during the disconnection

#### Scenario: cursor at terminal state

- **WHEN** a run has reached terminal state (`run_completed` or `run_failed`) and a client reconnects with a cursor that points to an event before the terminal event
- **THEN** the server SHALL deliver the terminal event
- **AND** the cursor SHALL NOT produce any new events after the terminal event

### Requirement: Reconnect replay completeness

The system SHALL replay all events after the cursor without loss. Replay SHALL preserve the original event order by `sequence`.

#### Scenario: no event loss on reconnect

- **WHEN** a client reconnects with a cursor and multiple events were produced after that cursor
- **THEN** the server SHALL replay every event after the cursor
- **AND** no event produced after the cursor SHALL be omitted from the replay

#### Scenario: event order preserved

- **WHEN** the server replays events after a cursor
- **THEN** the events SHALL be delivered to the client in ascending `sequence` order
- **AND** no event SHALL be delivered out of order relative to its `sequence`

### Requirement: Terminal state closes stream

The system SHALL close the SSE stream after emitting a terminal state event (`run_completed` or `run_failed`). A subsequent reconnect SHALL receive the terminal event and then have its stream closed.

#### Scenario: terminal event delivered then stream closes

- **WHEN** the server emits a `run_completed` or `run_failed` terminal event on an active stream
- **THEN** the server SHALL deliver the terminal event to the client
- **AND** the server SHALL close the SSE stream after delivering the terminal event

