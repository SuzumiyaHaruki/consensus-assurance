# Concrete CFT behavior to obligation and check

Recover actual behavior before deriving a Goal/Obligation. The families below are
conditional questions for CFT consensus / replicated state machines, not injected
claims or a fixed protocol specification. No historical bug is required.

## Selected behavior template

Behavior: <actor/role> handles <trigger> for <object/context>.
Purpose: why this effect matters to a system guarantee; related Goal if grounded.
Inputs / prerequisites: consumed facts/messages/state and their actual producers.
Actual implementation: checks, reads/writes, persistence, sends, callbacks and publication/return, with actual source ranges.
Branches: existing success, reject, duplicate, stale, timeout, error, partial-completion and configuration-dependent paths.
Semantic effect: what another component/node is allowed to infer after the event.
Existing protections: mechanisms that enforce or isolate the intended relation.
Interference / crossings: actual events that can change facts between establishment and use, including concurrent instances of this behavior.
Candidate obligation: a concrete relation with applicability and separate normative/contract and implementation sources.
Open question / suspicion: the uncertain fact or concrete legal path that may violate the relation.
Minimal discriminator: the smallest code check, direct execution, controlled schedule or local model that could distinguish the alternatives.

Use existing audit_question fields, sourced coverage points, scope and rationale.
Unknown producers remain questions, not assumed guarantees. A current guard is
not a normative obligation without independent contract/dependency justification.
"Ensure consistency" is not a checkable relation. Conditional liveness requires
supported verification and explicit fairness; do not silently turn it into an invariant.

## Conditional behavior questions

- Client/proposal establishment: Who may accept/establish this operation now? When
  is its position/context assigned? What changes or persists before publication?
  Can another request or context transition change a fact later consumed?
- Replication/request handling: What exact history/range does the request name?
  What do success, rejection and stale responses mean? Which local changes and
  persistence results precede success? Compare duplicate, partial, retry, error
  and alternate paths against their own applicable contracts. Consensus-layer
  deduplication is not a universal requirement.
- Response consumption/progress accounting: Which original request, peer/object
  and context owns the reply? What exact fact is learned? Can local progress,
  role/configuration change or object replacement reinterpret the old result?
  Trace original request metadata and isolation before alleging miscorrelation.
  Separate local quorum arithmetic/monotonicity, report provenance and actual
  command delivery; a checked accumulator does not discharge its producers.
- Election/role acquisition: What starts pre-election, if present, versus formal
  election? Which mechanisms are optional, disabled or bypassed on this path?
  What state changes before external vote/campaign effects? Which responses
  belong to which campaign instance/context? A candidate role need not advance
  a term; missing pre-election is not a defect.
- Role/authority loss: Which actual triggers revoke/change authority? Is a
  notification a completed transition or merely a request? Which in-flight work
  can finish, and which effects remain legal? Do not require lost-contact
  step-down; inspect the guarantees provided by the actual mechanism or alternative.
- Configuration/membership: Separate deciding/admitting a change from activation
  by each consumer. Which membership version governs each decision, election or
  replication action? How are old responses interpreted across activation?
  Joint consensus is not a universal requirement.
- Persistence/recovery: Which outward effect depends on which durable fact? What
  happens on crash/error between writes? What state is restored, and what work
  is discarded/recreated? Split writes alone do not prove an atomicity bug;
  inspect error handling, visibility and recovery reconstruction.
- Snapshot/compaction/catch-up: What history does capture represent? Separate
  capture semantics, persistence outcome, publication/visibility, reclamation
  authorization and recovery consumption. What may be reclaimed only once an
  alternative is usable? How does restored state rejoin incremental processing?
  Call order alone does not establish recoverability. Select the relevant store
  and configuration, retaining other adapters as explicit deferred dependencies;
  do not combine every store and failure mode into one question. A snapshot need
  not be the latest state or newly created before every legal deletion.
- Apply/completion: Distinguish committed, scheduled, executed and completed.
  Follow request identity through queues, batches, filtering and callback results
  to the matching completion. What do error, cancellation, restore or authority
  changes mean for eventual effects? Callback return is not automatically success
  of the service contract.

## Discover crossings along fact dependencies

For each selected behavior ask: Which other event can establish, mutate, replace,
invalidate, delete, or reinterpret a fact between this behavior's observation or
creation of it and a later consumer's use?

Candidates come from shared reads/writes, request/response identity, actual
role/context versions, object lifecycle/replacement, persistence completion,
configuration activation, snapshot/recovery/reclamation, background timers/control
loops and another instance of the same activity. Follow only dependencies relevant
to the current obligation, not a Cartesian product. Independent control loops and
non-atomic effects deserve examination where they share such a fact. Two orderings
with different outcomes are not by themselves a bug: check each applicable relation.
A phase name does not make an action atomic. Do not clear channels or synchronize
nodes without code evidence. Serialized event handling may isolate one path while
an asynchronous callback or exceptional bypass crosses that boundary.

Actively seek alternate guards, ownership/isolation, generation/context IDs,
serialized event loops, persistence-before-reply, cancellation/draining, later
validation and recovery reconstruction. If a protection explains a suspicion,
close or narrow it with sources and scope. Do not preserve a broad "unresolved"
label after the discriminator is answered. Preserve independent counterevidence.

Scope = behavior where the obligation is observable + causes needed to interpret
that effect + actual interfering activities that can change its meaning. Model
these from code; derive properties from obligations separately. Retain pending
work and identity when cross-context completion matters, with joint-history
reachability rather than unrelated reachable points. Several helpers can form one
behavior, and one behavior can require multiple actions. Excluded dependencies
remain explicit; an unverified producer must not become an idealized assumption.

## Compact next-stage handoff

Use the existing task_view/modeling_brief references and included objects once;
do not copy full review history. In the selected AuditQuestion and unit text retain:

- Question; why it matters (Goal); selected obligations.
- Concrete behavior/path, participants/objects/contexts and actual code ranges.
- Applicable configuration/variant; known protections with source references.
- Concrete suspicion or unresolved discriminator; relevant cross-activity interference.
- Explicit exclusions/deferred dependencies and relevant unresolved counterevidence.
- Preferred next check: code review / direct test / controlled schedule / local model;
  include legal prehistory, event relationship, actual observations and oracle.
- If modeling: variables/actions/checker and bounded reachability idea.

Use question for the discriminator, event_paths for behavior/protections/crossings,
contexts for variants, importance for consequence and trigger_rationale for the
preferred check and minimal scenario. Coverage-point unknowns and unit limitations
retain unresolved/excluded dependencies. Do not invent facts to fill a template.
An older workset without this detail needs a named evidence request, not inferred
protection. Dispositions are textual: explained_by_existing_mechanism,
concrete_suspicion, needs_specific_evidence or ready_for_check. They do not add
statuses, authorize semantic changes or bypass review and evidence checks.
