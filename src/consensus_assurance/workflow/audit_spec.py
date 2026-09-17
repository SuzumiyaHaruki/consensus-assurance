"""One descriptive implementation inventory; normative claims stay in the audit graph."""
import json
from pathlib import Path
from consensus_assurance.core.types import ConsensusAuditSpec
from consensus_assurance.adapters.storage.files import write_json

REFS = ('behavior_ids', 'fact_ids', 'handoff_ids')
IDENTITY = ('activity_classes', *REFS, 'obligation_relation_kind')


def load(state):
    return ConsensusAuditSpec.model_validate_json(Path(state.audit_spec_path).read_text()) if state.audit_spec_path else None



def validate_references(state, spec):
    """Report malformed draft references together; never invent missing semantic edges."""
    from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
    from .output_repair import pointer
    known={m.id for m in state.materials};bs={b.id:b for b in spec.behaviors};fs={f.id:f for f in spec.facts};hs={h.id:h for h in spec.handoffs};issues=[]
    def check(obj,path,field,allowed):
        values=getattr(obj,field);missing=set(values)-set(allowed)
        if missing:
            issues.append(Diagnostic(code='audit_spec_reference',category='material' if field=='source_ids' else 'format',object_ids=[obj.id] if hasattr(obj,'id') else [obj.class_id] if hasattr(obj,'class_id') else [],
                paths=[pointer(('audit_spec',*path,field))],message='Invalid '+field+' references: '+', '.join(sorted(missing)),allowed=['representation','read'] if field=='source_ids' else ['representation'],material_ids=sorted(set(values)&known) if field=='source_ids' else [],
                details={'field':field,'invalid_references':sorted(missing),'allowed_ids':sorted(allowed),
                    'instruction':'Use existing IDs only. Do not manufacture a producer guarantee or discard uncertainty; unread events belong in unknowns.'}))
    check(spec.target_profile,('target_profile',),'source_ids',known)
    for collection in ('activities','behaviors','facts','handoffs','coverage_summary','unclassified'):
        for i,obj in enumerate(getattr(spec,collection)):
            path=(collection,i);check(obj,path,'source_ids',known)
            fields={'activities':{'behavior_ids':bs,'fact_ids':fs,'handoff_ids':hs},'behaviors':{'produces_fact_ids':fs,'consumes_fact_ids':fs},
                'facts':{k:bs for k in ('established_by','consumed_by','invalidators','reinterpreters')},
                'handoffs':{'producer_behavior_ids':bs,'consumer_behavior_ids':bs},'coverage_summary':{'behavior_ids':bs},'unclassified':{'behavior_ids':bs}}[collection]
            for field,allowed in fields.items():check(obj,path,field,allowed)
    if issues:raise DiagnosticError(issues)


def validate(state, spec):
    from .sources import includes
    old = load(state)
    validate_references(state,spec)
    if spec.version != (old.version if old else 1):
        raise ValueError('Refine the current audit-spec version')
    groups = [spec.behaviors, spec.facts, spec.handoffs]
    ids = [x.id for group in groups for x in group]
    if len(ids) != len(set(ids)):
        raise ValueError('Audit-spec identifiers must be unique')
    behaviors = {b.id: b for b in spec.behaviors}; facts = {f.id: f for f in spec.facts}
    handoffs = {h.id: h for h in spec.handoffs}
    for obj in [spec.target_profile, *spec.activities, *sum(groups, []), *spec.coverage_summary, *spec.unclassified]:
        if not includes(state, obj.source_ids, [m.id for m in state.materials]):
            raise ValueError('Audit-spec cites unacquired source')
    for a in spec.activities:
        if not a.purpose.strip() or not a.realization_summary.strip():
            raise ValueError('Each activity needs an applicability explanation and realization or boundary')
        if a.applicability != 'unknown' and not a.source_ids:
            raise ValueError('Applicability and external ownership need source evidence')
        if a.applicability == 'unknown' and not a.unknowns:
            raise ValueError('Unknown applicability must name missing evidence')
        if set(a.coverage) != {'behavior', 'fact', 'handoff'}:
            raise ValueError('Record all three understanding dimensions')
        if not set(a.behavior_ids) <= behaviors.keys() or not set(a.fact_ids) <= facts.keys() or not set(a.handoff_ids) <= handoffs.keys():
            raise ValueError('Activity index references missing inventory')
        if a.applicability == 'applicable' and not (a.behavior_ids and a.entry_points) and not a.unknowns:
            raise ValueError('Applicable activity needs a skeleton or explicit missing evidence')
    for b in spec.behaviors:
        a = next(a for a in spec.activities if a.class_id == b.primary_activity)
        if b.id not in a.behavior_ids:
            raise ValueError('Primary activity must index its behavior')
    for f in spec.facts:
        if not f.meaning.strip() or not f.validity_context.strip() or not f.identity:
            raise ValueError('Fact needs semantic meaning, identity and validity context')
        for b in spec.behaviors:
            if (b.id in f.established_by) != (f.id in b.produces_fact_ids) or (b.id in f.consumed_by) != (f.id in b.consumes_fact_ids):
                raise ValueError('Producer/consumer indexes disagree')
    for h in spec.handoffs:
        if h.fact_id not in facts or not set(h.producer_behavior_ids) <= set(facts[h.fact_id].established_by) or not set(h.consumer_behavior_ids) <= set(facts[h.fact_id].consumed_by):
            from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
            paths=[] if old else [f'/audit_spec/handoffs/{spec.handoffs.index(h)}/fact_id','/audit_spec/facts/-'] + [f'/audit_spec/behaviors/{i}/{field}' for i,b in enumerate(spec.behaviors) if b.id in h.producer_behavior_ids+h.consumer_behavior_ids for field in ('produces_fact_ids','consumes_fact_ids')]
            raise DiagnosticError([Diagnostic(code='handoff_fact_semantics',category='semantic',object_ids=[h.id,h.fact_id,*h.producer_behavior_ids,*h.consumer_behavior_ids],material_ids=h.source_ids,paths=paths,allowed=['representation','read','stop'] if paths else ['read','stop'],
                message='Handoff must connect actual fact producers and consumers; distinguish the input prerequisite from the output effect',
                details={'instruction':'Only an unaccepted inventory may correct these diagnosed fact-flow references or append a sourced prerequisite fact. Preserve existing facts, unknowns, protections, claims and source dependencies. Do not invent an unread producer or convert an output effect into an input. Accepted inventory needs explicit semantic refinement.', 'handoff':h.model_dump(mode='json'),'fact':facts[h.fact_id].model_dump(mode='json') if h.fact_id in facts else None,
                    'behaviors':[b.model_dump(mode='json') for b in spec.behaviors if b.id in set(h.producer_behavior_ids+h.consumer_behavior_ids)]})])
        for key, bs in [(h.producer_activity,h.producer_behavior_ids),(h.consumer_activity,h.consumer_behavior_ids)]:
            if any(behaviors[b].primary_activity != key and key not in behaviors[b].cross_activity_effects for b in bs):
                raise ValueError('Handoff activity has no corresponding behavior effect')
    for surface in spec.coverage_summary + spec.unclassified:
        if not surface.reason.strip() or not set(surface.behavior_ids) <= behaviors.keys():
            raise ValueError('Reverse coverage needs a sourced disposition')
        if surface.disposition == 'mapped' and not surface.behavior_ids:
            raise ValueError('Mapped entry needs an actual behavior')
    if any(s.disposition != 'UNCLASSIFIED_PROTOCOL_RESPONSIBILITY' for s in spec.unclassified):
        raise ValueError('Unclassified inventory must remain explicit')
    if old:
        for name in ('behaviors', 'facts', 'handoffs'):
            if not {x.id for x in getattr(old,name)} <= {x.id for x in getattr(spec,name)}:
                raise ValueError('Refinement retains known implementation surface and its history')
        for a in spec.activities:
            prior = next(x for x in old.activities if x.class_id == a.class_id)
            if a.applicability != prior.applicability and (not a.source_ids or a.realization_summary == prior.realization_summary):
                raise ValueError('Applicability repair needs attributed new reasoning')
        used = {f for u in state.units if u.audit_question for f in u.audit_question.fact_ids}
        for f in old.facts:
            if f.id in used and (f.meaning, f.identity, f.validity_context) != (facts[f.id].meaning, facts[f.id].identity, facts[f.id].validity_context):
                raise ValueError('Selected fact meaning changes require attributed F2 before reconnecting the question')
    return spec


def accept(engine, spec):
    validate(engine.state, spec)
    old = load(engine.state)
    if old == spec:
        return
    spec = spec.model_copy(deep=True)
    spec.version = engine.state.audit_spec_version + 1
    path = engine.root / 'audit-spec' / f'v{spec.version}.json'
    write_json(path, spec)
    engine.state.audit_spec_path = str(path)
    engine.state.audit_spec_version = spec.version


def validate_question(spec, question):
    if not question or not question.activity_classes or not question.behavior_ids or not question.fact_ids or not question.obligation_relation_kind:
        raise ValueError('Active question needs activity, behavior, fact and lifecycle references')
    for field, collection in zip(REFS, ('behaviors','facts','handoffs')):
        if not set(getattr(question,field)) <= {x.id for x in getattr(spec,collection)}:
            raise ValueError('Question references absent audit-spec '+field)
    if question.obligation_relation_kind == 'cross_activity_handoff' and not question.handoff_ids:
        raise ValueError('Handoff question needs a concrete handoff')


def slice_for(state, question=None, classes=()):
    spec = load(state)
    if spec is None:
        return None
    if question is None and not classes:
        return spec.model_dump(mode='json')
    bs = set(question.behavior_ids if question else [])
    fs = set(question.fact_ids if question else [])
    hs = set(question.handoff_ids if question else [])
    selected = set(classes) | set(question.activity_classes if question else [])
    if not question:
        bs.update(b.id for b in spec.behaviors if b.primary_activity in selected)
        fs.update(f.id for f in spec.facts if set(f.established_by + f.consumed_by) & bs)
        hs.update(h.id for h in spec.handoffs if h.fact_id in fs)
    for h in spec.handoffs:
        if h.id in hs:fs.add(h.fact_id);bs.update(h.producer_behavior_ids+h.consumer_behavior_ids)
    for f in spec.facts:
        if f.id in fs:bs.update(f.established_by+f.consumed_by+f.invalidators+f.reinterpreters)
    selected.update(b.primary_activity for b in spec.behaviors if b.id in bs)
    return {'version':spec.version,'target_profile':spec.target_profile.model_dump(mode='json'),
        'activities':[a.model_dump(mode='json') for a in spec.activities if a.class_id in selected],
        **{name:[x.model_dump(mode='json') for x in getattr(spec,name) if x.id in ids] for name,ids in [('behaviors',bs),('facts',fs),('handoffs',hs)]}}


def refinement_reason(state):
    spec = load(state)
    if spec is None:return None  # Initial discovery enforces the spec; fixed backend fixtures are not discovery evidence.
    urgent = [s for s in spec.unclassified + spec.coverage_summary if s.high_consequence and s.disposition in {'deferred','UNCLASSIFIED_PROTOCOL_RESPONSIBILITY'}]
    if urgent:return 'Resolve high-consequence unmapped surface: '+ '; '.join(s.entry_point for s in urgent)
    if not spec.coverage_summary:return 'Reverse-check catalogue entry points against the seven-class inventory'
    if any(c.action in {'direct_check','model_check'} and 'spec-reviewed:'+c.id not in state.completed_steps for c in state.checks):
        return 'Integrate actual check evidence and reassess cross-activity priorities'
    return None


def reachability_refs(question):
    return set(sum((getattr(question,k) for k in REFS), [])) if question else set()


def coverage_ledger(state):
    spec = load(state)
    if spec is None:return []
    return [{'class_id':a.class_id,'applicability':a.applicability,'coverage':a.coverage,
        'obligation_ids':list(dict.fromkeys(id for u in state.units if u.audit_question and a.class_id in u.audit_question.activity_classes for id in u.obligation_ids)),
        'unit_ids':[u.id for u in state.units if u.audit_question and a.class_id in u.audit_question.activity_classes],
        'evidence_ids':[e.id for e in state.evidence if any(u.audit_question and a.class_id in u.audit_question.activity_classes and e.claim_id in u.obligation_ids for u in state.units)],
        'unknowns':a.unknowns} for a in spec.activities]


def source_ids(view):
    objects=[view['target_profile']]+[obj for name in ('activities','behaviors','facts','handoffs','coverage_summary','unclassified') for obj in view.get(name,[])]
    return {source for obj in objects for source in obj['source_ids']}
