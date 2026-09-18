# Implementation understanding and bounded obligation audit

## 1. Recover the target profile
Establish the system boundary, actual contexts, execution owners and storage/transport/application interfaces from code. selection_injection describes constructor/factory/caller selection and adapter ownership; variants describes actual protocol/configuration paths. Fault assumptions belong to the selected audit question. Caller injection does not externalize built-in repository implementations: inspect the chosen boundary and identify available variants without assuming activation.

## 2. Describe incomplete but coherent implementation behavior
Use seven parallel Activity coordinates from activity-classes.md, not seven execution stages. Each has sourced applicability/boundary or specific unknowns. Reverse-check APIs, handlers, timers, storage callbacks, recovery and deletion paths using one surfaces list. Retain UNCLASSIFIED_PROTOCOL_RESPONSIBILITY when necessary. Do not generate correctness claims in descriptive discovery.

A Behavior is one actor/execution owner handling one trigger in a concrete context. Split independent actors or branches establishing different semantic results before declaring fact edges. Keep legal prehistory, guards, reads/writes, durable/external effects, asynchronous boundaries, protections and unknowns.

A Fact asserts: given identity/context X, semantic assertion Y has been established. Observing a signal, requesting a transition and completing that transition are distinct assertions. Unknown producers or consumers are legal when recorded in unknowns. Behavior.produces_fact_ids/consumes_fact_ids are authoritative; reverse indices and cross-Activity relationships are derived. Do not bypass an unread semantic establishment merely because the adjacent endpoints are known.

## 3. Refine understanding at object level
Use spec_refine to add/split/reassign behaviors, refine/split facts, remove unsupported edges, and correct applicability, surfaces or ownership. Required diagnostic source belongs in the first refinement packet. Preserve unaccepted drafts and explicit unknowns; correcting an inventory is not evidence of correctness. Representation typos use mechanical repair; decomposition does not. An accepted question's referenced fact meaning, identity or validity context requires F2 and explicit reconnection.

## 4. Derive one bounded correctness question
After accepting a coherent inventory, select one principal Fact lifecycle: establishment, preservation, consumption or recovery. Derive one primary Obligation with normative/contract basis separate from implementation observations. AuditQuestion.importance explains the system consequence. Include actual legal scenario, relevant behaviors, existing protections, unresolved producer guarantees, one decisive discriminator and the preferred next check. Supporting obligations are dependencies, not additional simultaneously checked requirements. Avoid combining admission, replication, application, snapshot, restore and completion into one unit.

## 5. Obtain evidence and continue
Use source_review for uncertain semantics/applicability, direct_test for a controllable execution with an independent oracle, controlled_schedule for a few critical orderings with actual schedule control, and local_model for complex legal histories. Code defines behavior; the obligation defines the checker. Finite pass or TLC holds is not implementation proof; a local violation does not automatically establish a broader consequence.

Prefer ready high-value checks, then decisive selected-source gaps, then high-consequence unmapped surfaces. Ordinary unknowns remain inventory. After evidence, record the scoped conclusion and limitations, update understanding and choose the next obligation. Accepted understanding or apparent coverage is not audit success. No fixed protocol properties, target-specific answers or historical bugs are required.

Lifecycle meanings: establishment checks whether the fact a behavior claims to establish actually holds; preservation checks that an established fact remains valid until consumption; consumption checks whether a representation is interpreted as a stronger guarantee than it establishes; recovery checks re-establishment after crash, restart, loss or explicit invalidation. Continuing after an error alone is not recovery; acknowledgement from stale metadata usually raises establishment or consumption questions.

Externalized means the current audit boundary excludes the concrete implementation responsibility, not merely constructor injection. For caller-selected interfaces with in-repository variants, distinguish external selection, available implementations and an unknown currently used variant. Do not externalize unread built-in storage failure semantics by assumption.
