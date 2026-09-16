# Derive obligations from a concrete behavior

In the existing audit_question and modeling brief, explain one selected behavior:

Behavior: <actor/role> handles <trigger> for <object and position> in <execution
context and protocol/operation phase>.
Purpose: related goal/obligation IDs and why the effect matters.
Inputs: actual producers, source ranges, unresolved environment contracts.
Implementation: checks, reads/writes, storage, messages, publication/return.
Semantic effect: what a consumer may infer after the event.
Continuity: constraints retained, legally replaced, or invalidated on change.
Interference: actual queues, locks, callbacks, retries, delays, crashes and errors.
Obligations: testable state, transition or history relations with applicability.
Model plan: variables, actions, checkers, triggers and excluded dependencies.

This is a compact handoff view of existing G/O/C records, not another specification
or graph. Use audit_question.participants/objects/contexts/event_paths and sourced
coverage points; preserve unknowns rather than filling imaginary coordinates.
An actor x round x phase Cartesian product is unnecessary. A phase name does not
make a transition atomic. A behavior can require several actions; several helpers
can implement one behavior. Conditional liveness requires a suitable backend and
fairness assumptions; do not quietly convert it into an invariant.

Apply the questions relevant to the selected family:

- Proposal: Where do authority, position/parent history, value and supporting
  evidence come from? Does the sent content match the selected content? Can the
  context change between construction and publication? Do not mandate a highest
  certificate or knowledge of a global maximum.
- Support: What validates input and binds support to object, identity and phase?
  When does it become externally effective, and what future constraint does it
  establish? Different phases need not have the same support meaning.
- Aggregation: Which configuration determines eligibility, duplicate handling,
  weights and thresholds? Distinguish receipt, validation, persistence and use.
  Do not assume the very authenticity or history obligation being checked.
- Context/role change: How does pending old work finish or become isolated? What
  resets, survives or is transformed? Which evidence permits a legal change?
  Do not clear channels or synchronize all actors without code evidence.
- Membership/weight change: Separate deciding a change from each consumer's
  activation. How is historical evidence interpreted? Joint consensus is not a
  required universal mechanism; a recreated object can have a new lifecycle.
- Snapshot/history: Relate capture position, metadata, persistence, publication,
  reclamation and recovery/install consumers. Account for asynchronous progress
  and external storage/FSM responsibilities. A persisted snapshot need not be
  the latest state; deletion need not always follow a freshly created snapshot.
- Application/completion: Separate committed, scheduled, actually executed and
  completed effects. Derive batch filtering and response correlation from real
  sequences. A returned callback/result object is not automatically success of
  the application contract. Include errors and legal cancellation paths.

Check establishment, maintenance and use at producer/consumer boundaries. Missing
a familiar explicit guard is only a question: channels, object ownership, leases
or other isolation can provide an alternative. Put actual alternatives into the
behavior model, not a textbook guard. Model actions and source bindings must show
how the chosen checker and configured reachability trigger answer this question.
If cross-context work is claimed, retain pending work and its identity in actual
variables/actions and joint-history triggers. A local arithmetic unit can justify
excluding network history while leaving report authenticity as a separate gap.
