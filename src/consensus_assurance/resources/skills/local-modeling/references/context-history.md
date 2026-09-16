# Context and history in a local consensus question

Input: the selected question, attributed goals/obligations, actual source mappings and unresolved boundaries. Output: a compact context analysis in the Bundle, with links to concrete variables, actions, checkers and reachability requirements. This is an implementation abstraction, not a new normative specification.

Identify applicable dimensions independently: participant identity, operation/object identity, epoch/view, execution phase, position and configuration version. Unknown or inapplicable dimensions need a source-grounded explanation. Do not compress all dimensions into one global round.

Trace support through production, send, receive, acceptance, retention and consumption. Explain which guarantee each event establishes, the code implementing it and which upstream contracts remain unchecked. Different participants may occupy different contexts concurrently.

At a context change, retain outstanding requests, callbacks, messages and evidence unless actual code cancels, partitions or legally consumes them. An old operation may complete safely on its original object. Object or channel isolation can substitute for an explicit numeric-context comparison; missing a familiar guard alone is not a defect. Previously established facts may remain valid across context changes when the implementation permits it.

Separate in-context aggregation from replacement of the aggregation object or configuration. A monotonic update inside one object lifetime does not imply monotonic state across destruction and reconstruction. A phase name is not a lock or atomicity boundary. Split actions at observed queues, blocking calls, callbacks, lock release and persistence completion.

Distinguish volatile reconstruction from crash recovery; persistence survival follows the actual store contract. Same-context restart may be legal. Never inject Byzantine behavior into a crash-only scope or add an absent guard to satisfy a property.

For each modeled crossing, name the retained operation identity, source bindings, start/change/completion actions and the checker. Supply an executable same-history reachability requirement if claiming ordered interaction coverage. Separate reachable points cannot establish their ordered joint execution. State which dimensions, participants or paths are excluded. An arithmetic-only instance can mark cross-context networking not applicable while retaining report truth and configuration history as unchecked boundaries.

Check the emitted Behavior and actual TLC configuration: declared transitions must be enabled, checkers configured, trigger witnesses correlated to the same object/history. Agent explanation is a correspondence proposal; actual reachability and checker runs supply separate evidence. Never treat a single-node observation as evidence about unobserved participants.
