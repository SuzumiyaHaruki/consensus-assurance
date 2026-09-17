# Local behavior, semantic facts and obligations

For one actor/execution owner handling a trigger in a real protocol context, recover:
- Legal prehistory separately from actual implementation guards.
- Reads, writes, durable effects, external effects and exact acquired sources.
- Success/reject/stale/duplicate/timeout/error/partial/bypass branches that actually exist.
- Async boundaries, ownership, existing protections and named unknowns.
- Produced and consumed semantic facts; primary activity and cross-activity effects.

A fact is information a downstream behavior may legitimately rely on, not a raw variable. Record meaning, identity dimensions used by this implementation, representation, establishing and consuming behaviors, validity context, invalidators/reinterpreters, durability and recovery. An updated progress variable alone does not prove retained matching history; a published pointer alone does not prove recoverability. Source-grounded analysis must explain the distinction without injecting a target-specific answer.

Trace many-to-many Behavior→Fact→Behavior edges, including branches, merges, retries and cycles. For each selected fact ask which event can establish, mutate, replace, invalidate, delete or reinterpret it before consumption. Follow shared state, request identity, context changes, object lifecycle, persistence completion, configuration activation, recovery/reclamation and background work only where they affect this relation. Different ordering results are not themselves bugs: apply the obligation separately.

Conditioned checks:
- Establishment: permitted actor and context; identity assignment; state/persistence preceding publication; alternate admission paths.
- Replication/support: exact requested history/range; meaning of success/reject/stale; persistence preceding reply; original request ownership; duplicate/partial/error paths.
- Authority: actual pre-election/formal/context events, optional mechanisms and bypasses; durable vote state; old responses/work during transitions. No mandatory contact-loss stepdown.
- Configuration: decision/admission versus each consumer's activation; interpretation of in-flight evidence across versions.
- Recovery/history: outward effect dependent on durable facts; failures between writes; discarded/reconstructed work; snapshot capture versus persistence versus publication versus compaction authorization versus recovery consumption. Split persistence is not automatically a bug.
- Application/client: committed, scheduled, executed and completed are different facts; identity through batches/filtering/callbacks; late completion, retry/cancel, restore and read/barrier contracts.

For a suspicion, search alternate guard, object isolation, generation/context IDs, serialized loop, persistence-before-reply, cancellation/draining, later validation and recovery reconstruction. Record what each protection explains and what remains. Do not preserve a broad suspicion after its specific premise is refuted.

Derive an obligation only with its contract basis, observed implementation, applicability, protections and unexplained producer/consumer boundary. Label its lifecycle relation and cite spec IDs. Converge to explained_by_existing_mechanism, concrete_suspicion, needs_specific_evidence or ready_for_check. The handoff is a concise question, consequence, selected obligation, behavior/path, source ranges, variant/owner, protections, discriminator, interference, excluded dependencies and preferred check. If modeling, add actions/variables/checker and legal reachability idea. Do not copy review history into it.

Wire contract: coverage is exactly {"behavior":"unknown|partial|recovered", "fact":"unknown|partial|recovered", "handoff":"unknown|partial|recovered"}; judge each dimension separately, preserving the reasons in realization_summary/unknowns. cross_activity_effects maps an A1–A7 key to an effect description, never a feeds list or bare Behavior IDs. invalidators and reinterpreters contain existing Behavior IDs only; describe unlocated events in unknowns.

Behavior.produces_fact_ids and consumes_fact_ids are the authoritative edge declarations. The controller derives Fact.established_by/consumed_by and Activity.behavior_ids; do not redundantly generate them. A producer establishes a fact, not merely forwards evidence or receives a queue item. If commitment or another establishing step is unread, leave its producer unclaimed and record the precise missing source in Fact.unknowns. A received item is not proof of its producer's guarantee. Prefer a thin sourced inventory with explicit gaps over filling every edge.

Source pool view_id/source_view_id locate text only. Cite the original Material IDs listed in citation_ids, using the ranges that support the statement. Do not use a pooled text-view ID as an evidence identity.

A handoff carries a fact established before its consumer uses it. Do not use the consumer's resulting effect as its input prerequisite. If the prerequisite producer is unread, retain an explicit unknown instead of substituting a downstream result or inventing an edge.

Exact file:start:end citations within contiguous acquired ranges of the current snapshot can be registered by the shared reading service without new acquisition. This does not establish semantic support. Unread gaps require explicit reading; never remove a source dependency merely to satisfy identifier validation.
