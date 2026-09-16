# Thin CFT activity survey

Default: Crash Fault Tolerant (CFT) consensus / replicated state machines.
ABCD are overlapping coverage views, not stages or mandatory claims. Record
relevant activities as grounded, N/A with basis, unknown or deferred, with entry
points/roles, producers/consumers, shared state and handoffs. Responsibilities need not have Goals; avoid one model per activity.

| View | Conditional activity vocabulary |
| --- | --- |
| A: Decision progression | Establish/propose; receive/evaluate replication or proposals; produce/consume support; aggregate and advance commit/decision; learn/propagate decisions |
| B: Control and role/context | Timeout transitions where present; campaign/election; acquire/lose/transfer authority; membership activation; old in-flight work |
| C: Durable history and recovery | Durable protocol state; normal-path persistence/truncation; snapshot capture/persist/publish; catch-up/install/recovery; compaction/reclamation |
| D: Decision to service effects | Schedule/apply; batch filtering; response/Future correlation; reads/barriers; retry/cancel/restore |

Trace responsibilities to code and reverse-check APIs, message handlers, timers,
background loops, storage callbacks, startup/recovery and deletion paths. Follow
external adapters; include normal-path persistence.
Supported, enabled and used-on-this-path differ. Roles and timeout names do not
establish context changes. Do not require pre-election or automatic step-down on
lost contact. Inspect actual authority-maintenance triggers/effects, or what
maintains the relevant guarantee when that mechanism is absent.

Include crash/restart, storage error/order, stale replies and asynchronous work;
message delay/loss/duplicate/reorder only where the transport/fault model permits.
Prioritize consequence, unexplained handoffs, evidence and cost; defer other work.
Local arithmetic, report provenance and service delivery are distinct questions.
