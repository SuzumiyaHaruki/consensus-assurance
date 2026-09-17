# Implementation-grounded CFT audit

## 1. Recover the boundary and ownership
Use the catalogue, declarations and small source ranges to identify public APIs, message handlers, loops/timers, durable state, startup/recovery, configuration, application callbacks and completion paths. Prefer declaration-sized samples over whole-file reads. Recover actual contexts and external adapters, including constructor/factory/dependency injection. Distinguish supported, enabled and actually used variants; configuration need not be a flag. Role names are not semantics, and familiar optional mechanisms are not requirements.

## 2. Build the minimum seven-class understanding
Return a single ConsensusAuditSpec. Each class needs applicability, a realization or boundary explanation, entry points and behavior/fact/handoff skeletons or named missing evidence. Unknown is acceptable and must be explicit. Applicable, externalized and not_applicable judgments need actual sources; externalized names the responsible interface/caller. Do not create one goal or model per class. Do not split a class into local function steps.

Reverse-check important catalogue/declaration entries: mapped, externalized, infrastructure, deferred with reason, or UNCLASSIFIED_PROTOCOL_RESPONSIBILITY. Never force an important unclassified behavior into a class. High-consequence omissions deserve bounded refinement before repeatedly deepening one direction. Ordinary unknowns remain inventory, not automatic tasks.

## 3. Recover local behavior and semantic fact flow
Use references/behavior-facts.md. Follow the actual branches, owners, asynchronous boundaries and producer/consumer dependencies. A behavior is one triggered semantic processing point, not an entire distributed scenario. Record a primary class and cross-activity effects rather than duplicate behaviors. Multiple producers/consumers, branch/merge, retries and cycles are valid.

Inspect only interference capable of establishing, changing, replacing, deleting, invalidating or reinterpreting the selected fact between creation and use. Actively seek existing guards, ownership/isolation, context identity, serialization, persistence-before-publication, cancellation, later validation and recovery reconstruction. Explained suspicion should narrow or close; independent counterevidence stays visible.

## 4. Derive and select a question
Facts describe what the implementation establishes or consumes. Obligations state independently justified required relations: establishment, preservation, consumption, recovery or cross_activity_handoff. Keep normative source, implementation source, applicability and unresolved producer guarantees separate. Never copy a guard into an obligation or promote an unverified producer guarantee into an environment assumption.

Select by system consequence, cross-activity importance, actual evidence, remaining gap after protections, verification cost and neglected coverage. Goal explains the system consequence. AuditQuestion references existing spec IDs and one lifecycle relation; it carries legal prehistory, event paths, known protection, uncertainty and a minimal discriminator. Fixed protocol properties and target-specific answer keys are forbidden.

## 5. Obtain the smallest reliable evidence and integrate
If applicability or required meaning is unclear, request source_review. Prefer direct_test for one reachable execution with a reliable oracle; controlled_schedule requires actual schedule control. Use local_model when systematic exploration of legal histories/interleavings is the hard part. TLA+ is a method, not success itself. Scope includes observable behavior, causes needed to interpret its effect, and actual interfering activities.

After a check, reassess the seven-class ledger and next highest-value question. Refine descriptive ownership, applicability, behavior assignment, fact flow and handoffs from sources/evidence. Preserve previous spec versions. Changing accepted normative claims or a selected fact's meaning requires attributed F2; merely correcting implementation understanding does not. For a meaning change already used by a question, retain the old fact, introduce a sourced revised fact ID, then use an explicit F2 audit_question change to reconnect the existing unit. A descriptive refinement alone cannot reconnect accepted semantics. Never infer whole-activity or system correctness from finite execution/model bounds.

Keep the complete spec and raw reviews in the archive; local worksets contain selected spec slices, G/O/code, actual source, open counterevidence and current result. Summaries are not substitute source. Stop with a coverage ledger, not a claim of completeness.
