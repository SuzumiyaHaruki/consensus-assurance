# Responsibility and behavior survey

Use these four overlapping coverage views. They are not execution stages, a universal
protocol specification, or a proven complete taxonomy. This project's A/B/C/D are
not Specula's distributed/concurrent categories. Consult each applicable family;
record grounded N/A, unlocated paths or deferred work instead of manufacturing goals.
One behavior can serve multiple views without duplicating its graph objects.

| View | Families to investigate from actual entry points |
| --- | --- |
| A: Forming and learning decisions | Construct/send proposals; receive/evaluate proposals; produce/send support; collect support/form evidence; confirm/propagate/learn a decision |
| B: Protocol control and participation | Trigger/enter a context; acquire/transfer/revoke a role; export/collect/install handoff information; propose/activate changes in membership, weight or identity rules |
| C: Maintaining history, evidence and state | Update/save/publish protocol state; capture/persist/publish snapshots; transfer/recover/install history; truncate/reclaim/remove old state |
| D: Connecting decisions to service effects | Validate/schedule/execute commands; correlate/return results; provide read/barrier guarantees; retry/cancel/roll back work |

Move forward from these responsibilities to code mechanisms, then check backward
from APIs, message handlers, timers, background tasks, callbacks, startup recovery
and deletion paths. A directory sample does not establish responsibility coverage.
There need not be a stable leader, a single log, a uniform quorum rule, one decision
per round, or final decision before every speculative effect. Roles can overlap;
phases can be pipelined. Derive the relevant execution and object contexts from code.

Choose a meaningful bounded question by importance, unexamined interactions,
existing evidence, executable controls and cost. No historical issue or suspicious
guard is required. Preserve other responsibilities as explicit work; do not demand
17 goals, 17 models, or a reviewer call for each family before building one model.
