"""Descriptive implementation understanding, independent of correctness evidence."""
from pathlib import Path
from consensus_assurance.core.types import ConsensusAuditSpec, ACTIVITY_ROLES
from consensus_assurance.core.diagnostics import Diagnostic, DiagnosticError
from consensus_assurance.adapters.storage.files import write_json

REFS = ('behavior_ids', 'fact_ids')
IDENTITY = ('activity_classes', *REFS, 'obligation_relation_kind')
QUESTION_BASIS = ('audit_spec_version', *IDENTITY, 'supporting_behavior_ids', 'question', 'contexts', 'event_paths')


class SpecIssue(DiagnosticError):
    """An object-level understanding issue; not a mechanical output patch."""
    draft_path = None


def audit_object_key(obj):
    value=obj.model_dump() if hasattr(obj,'model_dump') else obj
    return 'surface:'+value['entry_point'] if 'entry_point' in value else value.get('id',value.get('class_id','target_profile' if 'system_boundary' in value else None))


def audit_object_index(spec):
    value=spec.model_dump(mode='json') if hasattr(spec,'model_dump') else spec or {}
    return {audit_object_key(o):o for o in [value.get('target_profile')]+[o for k in ('activities','behaviors','facts','surfaces') for o in value.get(k,[])] if o}


def audit_object_path(spec,key):
    value=spec.model_dump(mode='json') if hasattr(spec,'model_dump') else spec or {}
    if key=='target_profile':return '/target_profile'
    return next(('/'+k+'/'+str(i) for k in ('activities','behaviors','facts','surfaces') for i,o in enumerate(value.get(k,[])) if audit_object_key(o)==key),None)


def audit_object_sources(obj):
    return set(obj.source_ids if hasattr(obj,'source_ids') else (obj or {}).get('source_ids',[]))


def load(state):
    return ConsensusAuditSpec.model_validate_json(Path(state.audit_spec_path).read_text()) if state.audit_spec_path else None


def validate(state, spec, changes=None):
    old=load(state);issues=[];known={m.id for m in state.materials}
    behaviors={b.id:b for b in spec.behaviors};facts={f.id:f for f in spec.facts}
    objects=[spec.target_profile,*spec.activities,*spec.behaviors,*spec.facts,*spec.surfaces]
    def issue(obj,message,related=()):
        ids=[audit_object_key(obj),*related]
        sources=audit_object_sources(obj)
        for id in related:
            other=behaviors.get(id) or facts.get(id)
            if other:sources.update(other.source_ids)
        issues.append(Diagnostic(code='audit_spec_semantics',category='semantic',object_ids=ids,paths=[audit_object_path(spec,ids[0]) or '/'],material_ids=sorted(sources&known),details={'old':audit_object_index(old).get(ids[0]),'proposed':obj.model_dump(mode='json')},message=message,allowed=['read','semantic_revision']))
    if spec.version!=(old.version if old else 1):
        issue(spec.target_profile,f'Map base version conflict: expected {old.version if old else 1}, got {spec.version}; the controller assigns the accepted version')
    ids=[o.id for o in [*spec.behaviors,*spec.facts]]
    if len({s.entry_point for s in spec.surfaces})!=len(spec.surfaces):issue(spec.target_profile,'Duplicate surface entry points')
    if len(ids)!=len(set(ids)):issue(spec.target_profile,'Duplicate implementation object identifiers')
    for obj in objects:
        if not set(obj.source_ids)<=known:issue(obj,'Unacquired source references: '+', '.join(sorted(set(obj.source_ids)-known)))
    for a in spec.activities:
        if not a.purpose.strip() or not a.realization_summary.strip():issue(a,'Explain the actual responsibility or boundary')
        if a.applicability=='unknown' and not a.unknowns:issue(a,'Unknown applicability needs a specific missing fact')
        if a.applicability!='unknown' and not a.source_ids:issue(a,'Applicability needs actual source evidence')
        if set(a.behavior_ids)!={b.id for b in spec.behaviors if b.primary_activity==a.class_id}:issue(a,'Derived Activity index contradicts Behavior ownership')
    for b in spec.behaviors:
        if b.primary_activity not in {a.class_id for a in spec.activities}:issue(b,'Behavior needs its actual Activity coordinate')
        if not all(getattr(b,k).strip() for k in ('execution_owner','protocol_context','trigger')):issue(b,'Behavior needs its actual owner, context and trigger')
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
        if not s.reason.strip() or not s.source_ids or not set(s.behavior_ids)<=behaviors.keys() or s.disposition=='mapped' and not s.behavior_ids:issue(s,'Surface requires a sourced disposition and existing mapped behavior',s.behavior_ids)
    if issues:raise SpecIssue(issues)
    if changes is not None:
        before,after=audit_object_index(old),audit_object_index(spec)
        changed={key for key in before if object_content(before[key])!=object_content(after.get(key))}
        used={id for c in state.question_candidates if c.status!='explained' for id in c.question.fact_ids}
        added_producers={b.id for b in spec.behaviors if b.id not in before and set(b.produces_fact_ids)&used}
        if set(changes)!=changed|added_producers:
            raise ValueError('Map changes must explain modified objects and added producers of current principal Facts: '+', '.join(sorted(changed|added_producers)))
        structural={'identity','validity_context','primary_activity','execution_owner','protocol_context','produces_fact_ids','consumes_fact_ids','invalidators','reinterpreters'}
        for key,change in changes.items():
            if not set(change.source_ids)<=known:raise ValueError('Map change needs acquired source evidence: '+key)
            fields={k for k,v in object_content(before.get(key)).items() if object_content(after.get(key)).get(k)!=v}
            if change.impact=='clarification' and (key not in after or fields&structural):
                raise ValueError('Object removal or changed identity/context/edges is not descriptive clarification: '+key)
    return spec


def accept(engine,spec):
    """Persist the map validated against the transaction input, before new objects existed."""
    if load(engine.state)==spec:return
    spec=spec.model_copy(deep=True);spec.version=engine.state.audit_spec_version+1
    path=engine.root/'audit-spec'/f'v{spec.version}.json';write_json(path,spec)
    engine.state.audit_spec_path=str(path);engine.state.audit_spec_version=spec.version


def object_content(obj):
    return {k:v for k,v in (obj or {}).items() if k not in {'behavior_ids','established_by','consumed_by'}} if obj and ('class_id' in obj or 'meaning' in obj) else obj or {}


def validate_question(spec,question,focus=()):
    if not question or not question.activity_classes or not question.behavior_ids or len(question.fact_ids)!=1 or not question.obligation_relation_kind:
        raise ValueError('A bounded question needs one principal fact, lifecycle, behaviors and activity context')
    for field,collection in zip(REFS,('behaviors','facts')):
        if not set(getattr(question,field))<={x.id for x in getattr(spec,collection)}:raise ValueError('Question references absent '+field)
    if not set(question.activity_classes)<={a.class_id for a in spec.activities}:raise ValueError('Question references absent Activity')
    fact=next(f for f in spec.facts if f.id==question.fact_ids[0])
    linked=set(fact.established_by+fact.consumed_by+fact.invalidators+fact.reinterpreters)
    if not set(question.behavior_ids)<=linked:raise ValueError('Question Behavior must establish, consume, invalidate or reinterpret its principal Fact')
    support=question.supporting_behavior_ids
    if set(support)&set(question.behavior_ids) or not set(support)<={b.id for b in spec.behaviors} or any(not v.strip() for v in support.values()):
        raise ValueError('Causal support needs distinct existing Behavior IDs and their prehistory/context/consequence role')
    behaviors=[b for b in spec.behaviors if b.id in question.behavior_ids or b.id in support]
    responsibilities={b.primary_activity for b in behaviors}|{k for b in behaviors for k,v in b.cross_activity_effects.items() if v.strip()}
    if not set(question.activity_classes)<=responsibilities:raise ValueError('Activity labels need actual Behavior responsibility or attributed cross_activity_effects')
    if not any(ACTIVITY_ROLES[a]['role']=='core' for a in question.activity_classes):
        raise ValueError('Explain an A1 or A2 relationship through the selected sourced Behavior and necessary support; a supporting label alone is not a core question')
    if focus and not set(focus)&set(question.activity_classes)&responsibilities:raise ValueError('Explain the selected Fact lifecycle connection to the configured Activity focus')
    if not question.contexts or not question.event_paths or not question.importance.strip() or not question.trigger_rationale.strip():
        raise ValueError('Question needs actual contexts, event paths, consequence and selection reasoning')
    if not set(question.source_ids)&set(fact.source_ids) or any(not set(question.source_ids)&set(b.source_ids) for b in behaviors):
        raise ValueError('Question must cite its principal Fact and selected Behavior sources')


def require_basis(state,question,spec=None,focus=()):
    """An older basis remains valid when only unrelated or attributed descriptive objects change."""
    spec=spec or load(state)
    if spec is None:raise ValueError('Save the referenced Behavior/Fact map first')
    version=question.audit_spec_version if question else None
    if version is None:raise ValueError('Question needs its accepted audit_spec_version')
    if version!=spec.version:
        path=Path(state.audit_spec_path).parent/f'v{version}.json' if state.audit_spec_path else None
        if not path or not path.is_file() or version>state.audit_spec_version:raise ValueError('Question map version does not name an accepted basis')
        prior=ConsensusAuditSpec.model_validate_json(path.read_text())
        validate_question(prior,question,focus)
        old,new=audit_object_index(prior),audit_object_index(spec)
        dependencies=set(question.behavior_ids+question.fact_ids+list(question.supporting_behavior_ids))
        for key in dependencies:
            if object_content(old.get(key))==object_content(new.get(key)):continue
            declarations=[s['map_changes'][key] for s in state.selections
                if s.get('accepted_versions',{}).get('audit_spec',0)>version and key in s.get('map_changes',{})]
            if not declarations or any(d['impact']!='clarification' for d in declarations):
                raise ValueError('Question cites changed map semantics through an old version: '+key)
    validate_question(spec,question,focus)


def validate_reconnections(before,state,spec,changes):
    """Meaning and dependency changes use existing attributed graph revisions, not new gates."""
    changed={key:change for key,change in changes.items() if change.impact!='clarification'}
    old_spec=load(before)
    if old_spec is None:return
    old_index=audit_object_index(old_spec)
    for candidate in before.question_candidates:
        if candidate.status=='explained':continue
        q=candidate.question
        used=set(q.behavior_ids+q.fact_ids+list(q.supporting_behavior_ids))
        affected=used&changed.keys()
        for key in changed:
            if set(old_index.get(key,{}).get('produces_fact_ids',[])+old_index.get(key,{}).get('consumes_fact_ids',[]))&set(q.fact_ids):affected.add(key)
        added=[b for b in spec.behaviors if b.id not in old_index and b.id in changed and set(b.produces_fact_ids)&set(q.fact_ids)]
        if not affected and not added:continue
        current=next(c for c in state.question_candidates if c.id==candidate.id)
        if current.question.audit_spec_version!=spec.version:raise ValueError('Used map objects changed; explicitly reconnect Candidate '+candidate.id)
        if candidate.obligation_id:
            kind='F2' if any(changed[k].impact=='meaning' for k in affected) else 'F3'
            revisions=state.revisions[len(before.revisions):]
            units=[u for u in state.units if u.candidate_id==candidate.id and u.status!='revised']
            old_units=[u for u in before.units if u.candidate_id==candidate.id and u.status!='revised']
            if not any(r.kind==kind and set(r.target_ids)&{u.id for u in old_units} for r in revisions):
                raise ValueError('Used map change requires attributed '+kind+' and explicit Unit reconnection')
            if not units or any(u.audit_question.audit_spec_version!=spec.version for u in units):raise ValueError('Reconnect every current Unit to the changed map basis')


def validate_units(state,spec=None,focus=()):
    candidates={c.id:c for c in state.question_candidates}
    if sum(c.status=='active' for c in candidates.values())>1:raise ValueError('Only one active Candidate is allowed')
    owners=[u.candidate_id for u in state.units if u.status!='revised']
    if len(owners)!=len(set(owners)):raise ValueError('A Candidate has one current Unit; use independent check/model scenarios or an explicit scoped successor')
    for unit in state.units:
        if unit.status=='revised':continue
        c=candidates.get(unit.candidate_id)
        if c is None or c.obligation_id not in unit.obligation_ids:raise ValueError('Executable Unit needs its accepted Candidate and obligation: '+unit.id)
        require_basis(state,unit.audit_question,spec,focus)
        if any(getattr(unit.audit_question,k)!=getattr(c.question,k) for k in QUESTION_BASIS):
            raise ValueError('Unit and Candidate need an explicit shared question reconnection: '+unit.id)


def reachability_refs(question):
    return set(sum((getattr(question,k) for k in REFS),[])) if question else set()


def audit_progress(state):
    spec=load(state)
    if spec is None:return []
    return [{'class_id':audit_object_key(a),'applicability':a.applicability,'obligation_ids':list(dict.fromkeys(id for u in state.units if u.audit_question and a.class_id in u.audit_question.activity_classes for id in u.obligation_ids)),
        'evidence_ids':[e.id for e in state.evidence if any(u.audit_question and a.class_id in u.audit_question.activity_classes and e.claim_id in u.obligation_ids for u in state.units)],'unknowns':a.unknowns} for a in spec.activities]
