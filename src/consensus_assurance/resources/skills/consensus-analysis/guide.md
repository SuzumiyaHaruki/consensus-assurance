# CFT implementation-grounded analysis

Input: supplied code, attributed contracts/docs, configuration and the current
workset. Output: a thin responsibility map and a bounded actionable question in
existing G/O/C records. Default scope is Crash Fault Tolerant (CFT) consensus /
replicated state machines. Prior protocol knowledge suggests questions, not claims.
History may inform priority but neither a historical bug nor a supplied goal is
required. These steps are a reasoning order, not new controller stages.

## Step 0: Recover the target profile

Identify system boundary, roles actually present, actual term/epoch/round or
operation contexts, storage/transport/application ownership and relevant optional
mechanisms. Separate feature support, configured enablement and use on this path.
Role names are not semantics: entering a candidate role need not advance a term.
Do not normalize distinct contexts into one field. Missing a familiar mechanism
is not itself a defect. Trace external adapters when they own a required effect.

Include crash/restart, persistence ordering/errors, timeout, stale/late work,
concurrent instances and asynchronous completion. Delay/loss/duplicate/reorder
belong only where the actual transport/fault model permits them. Configuration,
snapshot, recovery, catch-up and commit-to-application paths are not optional
happy-path omissions; mark their applicability and unresolved dependencies.

## Step 1: Build a thin activity map

Use the loaded responsibilities-and-behaviors survey for overlapping ABCD coverage.
Find actual admission/proposal, replication/support exchange, commit/decision,
role maintenance, campaign, configuration, durable history, snapshot/recovery and
application/read activities. This vocabulary is not a required module list.
For each relevant activity record grounded, N/A (with basis), unknown or deferred,
entry points/roles, producers/consumers and shared state or handoffs. Use existing
Responsibility descriptions, applicability, questions and handoffs, not new enums.
Check both responsibility-to-code and entry-point-to-responsibility coverage.
Do not generate a Goal, Obligation or model for each activity.

## Step 2: Deep-analyze one important path

Select by system consequence, unexplained handoff, available evidence and cost,
not merely by how small a local function is. Use the loaded behavior-obligations
reference for the behavior template, conditional questions and interference rules.
Recover checks, effects and branches before deriving a relation. Locate actual
behavior ranges and definitions; one literal symbol per binding. A whole file or
an anchored call site does not establish a callee's behavior.

Trace facts from establishment through maintenance to use. Seek alternate guards,
ownership, serialization, deferred validation and recovery before retaining a
suspicion. An unverified producer guarantee is a question, not an environment
assumption. Expand only along the selected question's dependencies. Name the
smallest missing range and how its answer would change the next check.

## Step 3: Derive Goal and Obligation

A Goal explains a meaningful system guarantee and consequence. An Obligation is
a checkable relation required by that guarantee at an actual behavior or handoff.
Keep normative/contract sources separate from implementation sources; include
applicability, known protections and the unexplained producer/consumer boundary.
An explicitly derived producer/consumer contract is admissible with its derivation;
conflicting or unsupported expectations remain candidate judgments. Copying a
current guard does not establish what should hold. Avoid vague "ensure safety"
and do not invent a system Goal for every local detail.

Keep Goal meaning broad enough to explain significance while selecting only the
obligations and behavior necessary for this check. One behavior can raise several
questions, several obligations can share a model, and a binding does not require
its own review call. Preserve incomplete obligations and affected recheck work.

## Step 4: Close with an actionable audit question

Use one of these textual dispositions, not a new state machine:

- explained_by_existing_mechanism: cite the protection and the exact scope it explains.
- concrete_suspicion: identify a legal path and the applicable relation it may violate.
- needs_specific_evidence: name the missing fact/range and the decision it discriminates.
- ready_for_check: specify legal prehistory, event relation, observations and oracle.

Record the behavior and check plan in existing AuditQuestion question/event_paths,
contexts and trigger_rationale; importance connects to Goal; source_ids, bindings
and coverage points connect to actual ranges. Put exclusions in scope/coverage
limitations and unresolved facts in point unknowns. Responsibility questions can
retain explained or deferred work without manufacturing another audit unit.
Important handoffs need linked units, a sourced reason no separate check is needed,
or a bounded inquiry, even when both responsibilities already have goals.

The next-stage task_view/modeling brief uses the compact handoff in the behavior
reference, with the selected unit and sources included once. Keep full reasoning
and raw reviews in the archive; retain relevant unresolved counterevidence and
explicit resolutions in the current workset. Do not turn scope exclusions into
resolution of a semantic dispute. Successful local checks still invite semantic
review. A scoped result never discharges a whole Goal.
