"""Sourced questions, reusable conditional knowledge and explicitly answered premises."""
from consensus_assurance.core.types import Investigation, KnowledgeEntry, KnowledgeUse, Interpretation, Gap
from consensus_assurance.core.types import FixedExperiment


def require_sources(state, ids):
    known = {m.id for m in state.materials}
    if not ids or not set(ids) <= known:
        raise ValueError('Use acquired source Material IDs: ' + ', '.join(sorted(set(ids) - known)))


def require_uses(state, uses):
    entries = {e.id: e for e in state.knowledge}
    for use in uses:
        e = entries.get(use.entry_id)
        if e is None or use.revision not in {e.revision, *(h['revision'] for h in e.history)}:
            raise ValueError('Knowledge use must name an existing entry and exact revision')


def uses_of(state, entry_id, revision):
    objects = [(i.id, i.knowledge) for i in state.investigations]
    objects += [(a.id, FixedExperiment.model_validate(a).basis.knowledge) for a in state.experiments]
    objects += [(i.id, i.knowledge) for i in state.interpretations]
    return [id for id, uses in objects if any(u.entry_id == entry_id and u.revision == revision for u in uses)]


def investigation(state, id):
    current = next((i for i in state.investigations if i.id == id), None)
    if current is None:
        raise ValueError('Unknown investigation: ' + str(id))
    return current


def lineage(state, id):
    previous = {a.id: a.previous_id for a in state.experiments}
    result = set()
    while id:
        if id in result:
            raise ValueError('Experiment predecessor cycle')
        result.add(id)
        id = previous.get(id)
    return result


def open_gaps(state, investigation_id, experiment_id=None):
    owner = investigation(state, investigation_id)
    applicable = lineage(state, experiment_id) if experiment_id else set()
    answered = {id for i in state.interpretations if i.investigation_id == investigation_id
                and (experiment_id is None or i.experiment_id is None or i.experiment_id in applicable) for id in i.answers}
    return [g for g in owner.gaps if g.id not in answered and
            (experiment_id is None or g.experiment_id is None or g.experiment_id in applicable)]


def add_gap(state, owner_id, question, operation, experiment_id=None):
    owner = investigation(state, owner_id)
    if experiment_id:
        from .experiments import artifact
        if artifact(state, experiment_id).investigation_id != owner_id:
            raise ValueError('Gap experiment must belong to its investigation')
    existing = next((g for g in owner.gaps if g.question == question and g.experiment_id == experiment_id), None)
    if existing:
        return existing
    gap = Gap(id=operation + '-gap-' + str(sum(len(i.gaps) for i in state.investigations)),
              question=question, operation_id=operation, experiment_id=experiment_id)
    owner.gaps.append(gap)
    return gap


def resolve(ref, aliases):
    if ref and ref.startswith('@'):
        if ref not in aliases:
            raise ValueError('Unknown local batch reference: ' + ref)
        return aliases[ref]
    return ref


def bind_ref(ref, id, aliases):
    if ref:
        if not ref.startswith('@') or ref in aliases:
            raise ValueError('New batch references must be unique @names')
        aliases[ref] = id


def resolved_uses(uses, aliases):
    return [u.model_copy(update={'entry_id': resolve(u.entry_id, aliases)}) for u in uses]


def target_receipts(state, root, executions, *, owner_id=None, experiment_id=None, joint_history='', failure=None, support=True):
    from .experiments import artifact, observed, validate_failure, fixed_files
    from consensus_assurance.core.types import ExecutionStatus
    for id, indices in executions.items():
        c = next((c for c in state.checks if c.id == id), None)
        if c is None or c.action != 'experiment' or not c.experiment_id:
            raise ValueError('Cite actual target CheckRun IDs, not Agent or interpretation IDs')
        a = artifact(state, c.experiment_id)
        if c.snapshot_id != state.snapshot.id or c.snapshot_id != a.snapshot_id:
            raise ValueError('Referenced execution uses a different source snapshot')
        if ((experiment_id and a.id != experiment_id) or (owner_id and a.investigation_id != owner_id)) and not joint_history.strip():
            raise ValueError('A separate producer receipt needs explicit joint-history compatibility reasoning')
        measured = observed(a, c, root)
        events = measured['events']
        if len(set(indices)) != len(indices) or any(type(i) is not int or not 0 <= i < len(events) for i in indices):
            raise ValueError('Cite valid decisive parsed event indices, never raw line numbers')
        if not support:
            continue
        fixed_files(root, a)
        if c.status != ExecutionStatus.COMPLETED or not indices or measured['parsing_errors']:
            raise ValueError('Supporting observations require completed execution and intact parsed events')
        if c.parameters.get('changed_target_files') or c.parameters.get('lock_unchanged') is False:
            raise ValueError('Referenced execution changed protected inputs')
        if a.basis.harness.prerequisites and measured['prerequisites']['status'] != 'matched':
            raise ValueError('Referenced execution has unmatched prerequisites')
        if c.exit_code != 0 or c.outcome == 'not_applicable':
            if failure is None:
                raise ValueError('Referenced test failed or did not complete a selected test')
            validate_failure(state, root, a, c, measured, failure)


def update_knowledge(state, root, changes, operation, aliases):
    for number, change in enumerate(changes):
        require_sources(state, change.source_ids)
        target_receipts(state, root, change.executions)
        old = next((k for k in state.knowledge if k.id == change.id), None)
        if change.id and old is None:
            raise ValueError('Unknown knowledge entry')
        data = change.model_dump(exclude={'id', 'ref', 'changed_premise', 'affected_uses'})
        if old is None:
            old = next((k for k in state.knowledge if k.model_dump(exclude={'id','revision','history','operation_id'}) == data), None)
        id = old.id if old else operation + '-knowledge-' + str(number)
        bind_ref(change.ref, id, aliases)
        if old and old.model_dump(exclude={'id','revision','history','operation_id'}) == data:
            continue
        if change.affected_uses and not change.changed_premise.strip():
            raise ValueError('Explain which changed premise affects the recorded uses')
        used = uses_of(state, old.id, old.revision) if old else []
        if not set(change.affected_uses) <= set(used):
            raise ValueError('Correction names an object without the referenced knowledge revision')
        value = KnowledgeEntry(id=id, operation_id=operation, **data)
        if old:
            value.revision = old.revision + 1
            value.history = [*old.history, {**old.model_dump(exclude={'history'}),
                'correction': change.changed_premise, 'recorded_uses': used, 'affected_uses': change.affected_uses}]
            state.knowledge[state.knowledge.index(old)] = value
        else:
            state.knowledge.append(value)
        for target in change.affected_uses:
            owner = next((i for i in state.investigations if i.id == target), None)
            fixed = next((a for a in state.experiments if a.id == target), None)
            opinion = next((i for i in state.interpretations if i.id == target), None)
            owner_id = owner.id if owner else fixed.investigation_id if fixed else opinion.investigation_id
            experiment_id = fixed.id if fixed else opinion.experiment_id if opinion else None
            add_gap(state, owner_id, 'Knowledge ' + id + ': ' + change.changed_premise, operation, experiment_id)


def update_questions(state, changes, operation, aliases):
    for number, change in enumerate(changes):
        old = investigation(state, change.id) if change.id else None
        data = old.model_dump(exclude={'id','version','history','operation_id','gaps'}) if old else {}
        data.update(change.model_dump(exclude={'id','ref'}, exclude_unset=True))
        if data.get('parent_id'):
            data['parent_id'] = resolve(data['parent_id'], aliases)
            investigation(state, data['parent_id'])
        if data.get('knowledge') is not None:
            data['knowledge'] = resolved_uses([KnowledgeUse.model_validate(u) for u in data['knowledge']], aliases)
        value = Investigation(id=old.id if old else operation + '-question-' + str(number), operation_id=operation, **data)
        require_sources(state, value.source_ids)
        if not any(m.id in value.source_ids and m.file in state.snapshot.files for m in state.materials):
            raise ValueError('A question needs an actual captured source')
        require_uses(state, value.knowledge)
        if value.parent_id == value.id:
            raise ValueError('An investigation cannot be its own parent')
        ancestor = value.parent_id
        while ancestor:
            if ancestor == value.id:
                raise ValueError('Investigation parent cycle')
            ancestor = investigation(state, ancestor).parent_id
        if value.disposition == 'paused' and not value.resume_conditions:
            raise ValueError('A paused question needs concrete resume conditions')
        if value.disposition != 'paused' and value.resume_conditions:
            raise ValueError('Resume conditions belong to a paused question')
        effective = value.model_dump(exclude={'id','version','history','operation_id','gaps'})
        if old is None:
            old = next((i for i in state.investigations if i.model_dump(exclude={'id','version','history','operation_id','gaps'}) == effective), None)
        bind_ref(change.ref, old.id if old else value.id, aliases)
        if old:
            if old.model_dump(exclude={'id','version','history','operation_id','gaps'}) == effective:
                continue
            value.id = old.id
            value.version = old.version + 1
            value.history = [*old.history, old.model_dump(exclude={'history','gaps'})]
            value.gaps = old.gaps
            state.investigations[state.investigations.index(old)] = value
        else:
            state.investigations.append(value)


def interpret(state, root, changes, operation, aliases):
    for number, change in enumerate(changes):
        data = change.model_dump(mode='json')
        data['investigation_id'] = resolve(change.investigation_id, aliases)
        owner = investigation(state, data['investigation_id'])
        data['knowledge'] = resolved_uses(change.knowledge, aliases)
        require_sources(state, change.source_ids)
        require_uses(state, data['knowledge'])
        if change.experiment_id:
            from .experiments import artifact
            if artifact(state, change.experiment_id).investigation_id != owner.id:
                raise ValueError('Interpretation must identify its investigation and fixed experiment')
            if not any(c.experiment_id == change.experiment_id and c.id in change.executions for c in state.checks):
                raise ValueError('An experiment interpretation needs its own actual execution')
        target_receipts(state, root, change.executions, owner_id=owner.id, experiment_id=change.experiment_id,
                        joint_history=change.joint_history, failure=change.failure_attribution,
                        support=change.conclusion in {'violated', 'holds'})
        gaps = {g.id: g for g in owner.gaps}
        if not set(change.answers) <= gaps.keys() or any(not v.strip() for v in change.answers.values()):
            raise ValueError('Answer this investigation\'s exact registered gaps with substantive reasoning')
        if change.experiment_id and any(gaps[id].experiment_id and
                gaps[id].experiment_id not in lineage(state, change.experiment_id) for id in change.answers):
            raise ValueError('Answer only gaps belonging to this experiment lineage, or give a source-only correction')
        if change.conclusion in {'violated','holds'} and not change.experiment_id:
            raise ValueError('Measured conclusions require a fixed experiment; source-only answers use explained or unresolved')
        value = Interpretation(id=operation + '-interpretation-' + str(number), operation_id=operation, **data)
        effective = value.model_dump(exclude={'id','operation_id'})
        prior = next((i for i in reversed(state.interpretations) if i.investigation_id == owner.id and i.experiment_id == change.experiment_id), None)
        if prior is None or prior.model_dump(exclude={'id','operation_id'}) != effective:
            state.interpretations.append(value)
