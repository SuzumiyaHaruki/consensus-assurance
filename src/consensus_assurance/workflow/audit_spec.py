"""Descriptive implementation understanding, independent of correctness evidence."""
from pathlib import Path
from consensus_assurance.core.types import ConsensusAuditSpec
from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
from consensus_assurance.adapters.storage.files import write_json

REFS = ('behavior_ids', 'fact_ids')
IDENTITY = ('activity_classes', *REFS, 'obligation_relation_kind')


class SpecIssue(DiagnosticError):
    """An object-level understanding issue; not a mechanical output patch."""
    draft_path = None


def load(state):
    return ConsensusAuditSpec.model_validate_json(Path(state.audit_spec_path).read_text()) if state.audit_spec_path else None


def validate(state, spec):
    old=load(state);issues=[];known={m.id for m in state.materials}
    behaviors={b.id:b for b in spec.behaviors};facts={f.id:f for f in spec.facts}
    objects=[spec.target_profile,*spec.activities,*spec.behaviors,*spec.facts,*spec.surfaces]
    def issue(obj,message,related=()):
        ids=[getattr(obj,'id',getattr(obj,'class_id',getattr(obj,'entry_point','target_profile'))),*related]
        sources=set(obj.source_ids)
        for id in related:
            other=behaviors.get(id) or facts.get(id)
            if other:sources.update(other.source_ids)
        issues.append(Diagnostic(code='audit_spec_semantics',category='semantic',object_ids=ids,material_ids=sorted(sources&known),message=message,allowed=['read','semantic_revision']))
    if spec.version!=(old.version if old else 1):issue(spec.target_profile,'Refine the current inventory version')
    ids=[o.id for o in [*spec.behaviors,*spec.facts]]
    if len(ids)!=len(set(ids)):issue(spec.target_profile,'Duplicate implementation object identifiers')
    for obj in objects:
        if not set(obj.source_ids)<=known:issue(obj,'Unacquired source references: '+', '.join(sorted(set(obj.source_ids)-known)))
    for a in spec.activities:
        if not a.purpose.strip() or not a.realization_summary.strip():issue(a,'Explain the actual responsibility or boundary')
        if a.applicability=='unknown' and not a.unknowns:issue(a,'Unknown applicability needs a specific missing fact')
        if a.applicability!='unknown' and not a.source_ids:issue(a,'Applicability needs actual source evidence')
    for b in spec.behaviors:
        missing=set(b.produces_fact_ids+b.consumes_fact_ids)-facts.keys()
        if missing:issue(b,'Behavior references nonexistent facts',sorted(missing))
    for f in spec.facts:
        if not f.meaning.strip() or not f.identity or not f.validity_context.strip():issue(f,'Fact needs an identity-scoped semantic assertion')
        missing=set(f.established_by+f.consumed_by+f.invalidators+f.reinterpreters)-behaviors.keys()
        if missing:issue(f,'Fact references nonexistent behaviors',sorted(missing))
        if (not f.established_by or not f.consumed_by) and not f.unknowns:issue(f,'An unknown producer or consumer requires an explicit unknown')
        for b in spec.behaviors:
            if (b.id in f.established_by)!=(f.id in b.produces_fact_ids) or (b.id in f.consumed_by)!=(f.id in b.consumes_fact_ids):issue(f,'Derived fact index contradicts the authoritative behavior edges',[b.id])
    for s in spec.surfaces:
        if not s.reason.strip() or not set(s.behavior_ids)<=behaviors.keys() or s.disposition=='mapped' and not s.behavior_ids:issue(s,'Surface requires a supported disposition and existing mapped behavior',s.behavior_ids)
    if old:
        for unit in state.units:
            if unit.audit_question and unit.audit_question.fact_ids:validate_question(spec,unit.audit_question)
        used={f for u in state.units if u.audit_question for f in u.audit_question.fact_ids}
        for f in old.facts:
            if f.id in used and (f.id not in facts or any(getattr(f,k)!=getattr(facts[f.id],k) for k in ('meaning','identity','validity_context'))):
                raise ValueError('Selected fact meaning requires attributed F2 and explicit question reconnection')
    if issues:raise SpecIssue(issues)
    return spec


def accept(engine,spec):
    validate(engine.state,spec)
    if load(engine.state)==spec:return
    spec=spec.model_copy(deep=True);spec.version=engine.state.audit_spec_version+1
    path=engine.root/'audit-spec'/f'v{spec.version}.json';write_json(path,spec)
    engine.state.audit_spec_path=str(path);engine.state.audit_spec_version=spec.version


def validate_question(spec,question):
    if not question or not question.activity_classes or not question.behavior_ids or len(question.fact_ids)!=1 or not question.obligation_relation_kind:
        raise ValueError('A bounded question needs one principal fact, lifecycle, behaviors and activity context')
    for field,collection in zip(REFS,('behaviors','facts')):
        if not set(getattr(question,field))<={x.id for x in getattr(spec,collection)}:raise ValueError('Question references absent '+field)


def slice_for(state,question=None,classes=()):
    spec=load(state)
    if spec is None:return None
    if question is None and not classes:return spec.model_dump(mode='json')
    bs=set(question.behavior_ids if question else []);fs=set(question.fact_ids if question else [])
    selected=set(classes)|set(question.activity_classes if question else [])
    if not question:bs.update(b.id for b in spec.behaviors if b.primary_activity in selected)
    fs.update(f.id for f in spec.facts if set(f.established_by+f.consumed_by)&bs)
    for f in spec.facts:
        if f.id in fs:bs.update(f.established_by+f.consumed_by+f.invalidators+f.reinterpreters)
    selected.update(b.primary_activity for b in spec.behaviors if b.id in bs)
    return {'version':spec.version,'target_profile':spec.target_profile.model_dump(mode='json'),'activities':[a.model_dump(mode='json') for a in spec.activities if a.class_id in selected],
        'behaviors':[b.model_dump(mode='json') for b in spec.behaviors if b.id in bs],'facts':[f.model_dump(mode='json') for f in spec.facts if f.id in fs],
        'surfaces':[s.model_dump(mode='json') for s in spec.surfaces if set(s.behavior_ids)&bs]}


def refinement_reason(state):
    spec=load(state)
    if spec is None:return None
    # A tractable evidence path takes priority over more descriptive completeness.
    if any(u.status in {'pending','partial'} and u.audit_question and u.audit_question.disposition=='ready_for_check' for u in state.units):return None
    urgent=[s for s in spec.surfaces if s.high_consequence and s.disposition in {'deferred','UNCLASSIFIED_PROTOCOL_RESPONSIBILITY'}]
    if urgent:return 'Resolve high-consequence surface: '+'; '.join(s.entry_point for s in urgent)
    if any(c.action in {'direct_check','model_check'} and 'spec-reviewed:'+c.id not in state.completed_steps for c in state.checks):return 'Integrate evidence and select the next obligation'
    return None


def reachability_refs(question):
    return set(sum((getattr(question,k) for k in REFS),[])) if question else set()


def audit_progress(state):
    spec=load(state)
    if spec is None:return []
    return [{'class_id':a.class_id,'applicability':a.applicability,'obligation_ids':list(dict.fromkeys(id for u in state.units if u.audit_question and a.class_id in u.audit_question.activity_classes for id in u.obligation_ids)),
        'evidence_ids':[e.id for e in state.evidence if any(u.audit_question and a.class_id in u.audit_question.activity_classes and e.claim_id in u.obligation_ids for u in state.units)],'unknowns':a.unknowns} for a in spec.activities]


def source_ids(view):
    return {id for obj in [view['target_profile']]+[o for name in ('activities','behaviors','facts','surfaces') for o in view.get(name,[])] for id in obj['source_ids']}


def issue_groups(diagnostics):
    """Connected diagnostic objects share one source-complete refinement packet."""
    groups=[]
    for diagnostic in diagnostics:
        ids=set(diagnostic['object_ids']);joined=[];rest=[]
        for group in groups:
            if ids & {id for d in group for id in d['object_ids']}:joined.extend(group)
            else:rest.append(group)
        groups=rest+[joined+[diagnostic]]
    return groups
