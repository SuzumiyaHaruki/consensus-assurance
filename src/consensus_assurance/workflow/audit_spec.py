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
    return {**{audit_object_key(o):o for o in [value.get('target_profile')]+[o for k in ('activities','behaviors','facts','surfaces') for o in value.get(k,[])] if o}, **({'core_overview':value['core_overview']} if value.get('core_overview') else {})}


def audit_object_path(spec,key):
    value=spec.model_dump(mode='json') if hasattr(spec,'model_dump') else spec or {}
    if key in {'target_profile','core_overview'}:return '/'+key
    return next(('/'+k+'/'+str(i) for k in ('activities','behaviors','facts','surfaces') for i,o in enumerate(value.get(k,[])) if audit_object_key(o)==key),None)


def audit_object_sources(obj):
    return set(obj.source_ids if hasattr(obj,'source_ids') else (obj or {}).get('source_ids',[]))


def load(state):
    return ConsensusAuditSpec.model_validate_json(Path(state.audit_spec_path).read_text()) if state.audit_spec_path else None


def validate(state, spec, changes=None, unavailable=()):
    old=load(state);issues=[];known={m.id for m in state.materials}|set(unavailable)
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
    ids=[audit_object_key(o) for o in objects]+['core_overview']
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
        if not b.source_ids:issue(b,'Behavior requires actual source evidence')
        if b.primary_activity not in {a.class_id for a in spec.activities}:issue(b,'Behavior needs its actual Activity coordinate')
        if not all(getattr(b,k).strip() for k in ('execution_owner','protocol_context','trigger')):issue(b,'Behavior needs its actual owner, context and trigger')
        missing=set(b.produces_fact_ids+b.consumes_fact_ids)-facts.keys()
        if missing:issue(b,'Behavior references nonexistent facts',sorted(missing))
    for f in spec.facts:
        if not f.source_ids:issue(f,'Fact requires actual source evidence')
        if not f.meaning.strip() or not f.identity or not f.validity_context.strip():issue(f,'Fact needs an identity-scoped semantic assertion')
        missing=set(f.established_by+f.consumed_by+f.invalidators+f.reinterpreters)-behaviors.keys()
        if missing:issue(f,'Fact references nonexistent behaviors',sorted(missing))
        if (not f.established_by or not f.consumed_by) and not f.unknowns:issue(f,'An unknown producer or consumer requires an explicit unknown')
        for b in spec.behaviors:
            if (b.id in f.established_by)!=(f.id in b.produces_fact_ids) or (b.id in f.consumed_by)!=(f.id in b.consumes_fact_ids):issue(f,'Derived fact index contradicts the authoritative behavior edges',[b.id])
    for s in spec.surfaces:
        if not s.reason.strip() or not s.source_ids or not set(s.behavior_ids)<=behaviors.keys() or s.disposition=='mapped' and not s.behavior_ids:issue(s,'Surface requires a sourced disposition and existing mapped behavior',s.behavior_ids)
    overview=spec.core_overview
    if overview:
        def overview_issue(path,message):
            issues.append(Diagnostic(code='core_overview',category='semantic',paths=['/core_overview/'+path],
                message=message,allowed=['read','semantic_revision']))
        if not overview.rationale.strip():overview_issue('rationale','Explain why the initial backbone is usable, incomplete or blocked')
        if overview.status!='usable' and not overview.core_gaps:
            overview_issue('core_gaps','Name the missing backbone or unavailable source/boundary')
        if overview.status=='usable' and overview.core_gaps:
            overview_issue('status','A declared core break cannot be a usable initial overview; details may remain open')
        for name in ('formation','context','connection'):
            path=getattr(overview,name)
            for field,known_refs in [('behavior_ids',behaviors),('fact_ids',facts),('source_ids',known)]:
                missing=set(getattr(path,field))-set(known_refs)
                if missing:overview_issue(name+'/'+field,'Unknown overview references: '+', '.join(sorted(missing)))
            if overview.status!='usable':continue
            if not path.explanation.strip() or not path.behavior_ids or not path.fact_ids or not path.source_ids:
                overview_issue(name,'A usable path needs explanation and Behavior, Fact and source references')
            selected=[behaviors[b] for b in path.behavior_ids if b in behaviors]
            roles={b.primary_activity for b in selected}|{k for b in selected for k,v in b.cross_activity_effects.items() if v.strip()}
            required={'formation':{'A1'},'context':{'A2'},'connection':{'A1','A2'}}[name]
            if not required<=roles:overview_issue(name+'/behavior_ids','Explain the actual core responsibilities: '+', '.join(sorted(required-roles)))
            objects=selected+[facts[f] for f in path.fact_ids if f in facts]
            if any(not set(path.source_ids)&set(o.source_ids) for o in objects):
                overview_issue(name+'/source_ids','Cite the referenced Behavior and Fact sources; labels alone do not explain a path')
    if issues:raise SpecIssue(issues)
    if changes is not None and not unavailable:understanding_changes(state,spec,changes)
    return spec


def require_overview(state, spec):
    if not (state.config.get('directed_question') or '').strip() and (not spec or not spec.core_overview or spec.core_overview.status!='usable'):
        raise ValueError('Initial core understanding is incomplete: retain partial research and recover both core paths and their connection before focused Candidates or formal checks')


def accept(engine,spec):
    """Persist the map validated against the transaction input, before new objects existed."""
    if not map_delta(load(engine.state),spec):return
    spec=spec.model_copy(deep=True);spec.version=engine.state.audit_spec_version+1
    path=engine.root/'audit-spec'/f'v{spec.version}.json';write_json(path,spec)
    engine.state.audit_spec_path=str(path);engine.state.audit_spec_version=spec.version


def object_content(obj):
    return {k:v for k,v in (obj or {}).items() if k not in {'behavior_ids','established_by','consumed_by'}} if obj and ('class_id' in obj or 'meaning' in obj) else obj or {}


def validate_question(spec,question,focus=()):
    if not question or not question.activity_classes or not question.behavior_ids or len(question.fact_ids)!=1 or not question.obligation_relation_kind:
        raise ValueError('A bounded question needs one principal fact, lifecycle, behaviors and activity context')
    errors=[]
    for field,collection in zip(REFS,('behaviors','facts')):
        if not set(getattr(question,field))<={x.id for x in getattr(spec,collection)}:errors.append('Question references absent '+field+': '+', '.join(sorted(set(getattr(question,field))-{x.id for x in getattr(spec,collection)})))
    if not set(question.activity_classes)<={a.class_id for a in spec.activities}:errors.append('Question references absent Activity: '+', '.join(sorted(set(question.activity_classes)-{a.class_id for a in spec.activities})))
    fact=next((f for f in spec.facts if f.id==question.fact_ids[0]),None)
    linked=set(fact.established_by+fact.consumed_by+fact.invalidators+fact.reinterpreters) if fact else set()
    if fact and not set(question.behavior_ids)<=linked:errors.append('Question Behavior must establish, consume, invalidate or reinterpret its principal Fact')
    support=question.supporting_behavior_ids
    if set(support)&set(question.behavior_ids) or not set(support)<={b.id for b in spec.behaviors} or any(not v.strip() for v in support.values()):
        errors.append('Causal support needs distinct existing Behavior IDs and their prehistory/context/consequence role')
    behaviors=[b for b in spec.behaviors if b.id in question.behavior_ids or b.id in support]
    responsibilities={b.primary_activity for b in behaviors}|{k for b in behaviors for k,v in b.cross_activity_effects.items() if v.strip()}
    if not set(question.activity_classes)<=responsibilities:errors.append('Activity labels need actual Behavior responsibility or attributed cross_activity_effects')
    if not any(ACTIVITY_ROLES[a]['role']=='core' for a in question.activity_classes):
        errors.append('Explain an A1 or A2 relationship through the selected sourced Behavior and necessary support; a supporting label alone is not a core question')
    if focus and not set(focus)&set(question.activity_classes)&responsibilities:errors.append('Explain the selected Fact lifecycle connection to the configured Activity focus')
    if not question.contexts or not question.event_paths or not question.importance.strip() or not question.trigger_rationale.strip():
        errors.append('Question needs actual contexts, event paths, consequence and selection reasoning')
    if (fact and not set(question.source_ids)&set(fact.source_ids)) or any(not set(question.source_ids)&set(b.source_ids) for b in behaviors):
        errors.append('Question must cite its principal Fact and selected Behavior sources')

    if errors:raise ValueError("; ".join(errors))


def map_delta(before, after):
    """Derive actual knowledge edits; only reverse indexes are mechanical."""
    old,new=audit_object_index(before),audit_object_index(after)
    return {key:{'before':object_content(old.get(key)), 'after':object_content(new.get(key))}
        for key in sorted(old.keys()|new.keys()) if object_content(old.get(key))!=object_content(new.get(key))}


def understanding_changes(state, spec, changes):
    """One impact contract, shared by acceptance and historical basis validation.

    Citations and graph references are checked mechanically. Preserved and challenged
    propositions are sourced interpretations, still open to substantive review.
    """
    old=load(state)
    delta=map_delta(old,spec)
    known={m.id for m in state.materials}
    candidates={c.id:c for c in state.question_candidates}
    related={}
    for id,c in candidates.items():
        q=c.question
        used=set(q.behavior_ids+q.fact_ids+list(q.supporting_behavior_ids))
        related[id]={key for key,d in delta.items() if key in used or
            any(set(obj.get('produces_fact_ids',[])+obj.get('consumes_fact_ids',[]))&set(q.fact_ids)
                for obj in d.values())}
    required={key for key,d in delta.items() if d['before']} | set().union(*related.values(),set())
    missing=required-changes.keys() if old else set()
    unknown=changes.keys()-audit_object_index(old).keys()-audit_object_index(spec).keys()
    if missing or unknown:
        raise ValueError('Map change explanations: missing='+str(sorted(missing))+'; unknown='+str(sorted(unknown)))
    for key in list(changes):
        if key not in delta:changes.pop(key)
    for key,d in delta.items():
        if d['before'] and d['after'] and ('meaning' in d['before'])!=('meaning' in d['after']):
            raise ValueError('Map object identity cannot change between Behavior and Fact: '+key)
    structural={'identity','validity_context','primary_activity','execution_owner','protocol_context',
        'produces_fact_ids','consumes_fact_ids','invalidators','reinterpreters'}
    effects={id:[] for id in candidates}
    for key,change in changes.items():
        if not set(change.source_ids)<=known:raise ValueError('Map change needs acquired source evidence: '+key)
        if not set(change.challenges)<=candidates.keys() or any(not reason.strip() for reason in change.challenges.values()):
            raise ValueError('Map challenges need saved Candidate IDs and specific reasons: '+key)
        d=delta[key]
        fields={k for k in d['before'].keys()|d['after'].keys() if d['before'].get(k)!=d['after'].get(k)}
        if change.impact=='clarification' and (not d['after'] or fields&structural):
            raise ValueError('Object removal or changed identity/context/edges is not descriptive clarification: '+key)
        for id in candidates:
            challenged=change.challenges.get(id)
            if key not in related[id] and not challenged:continue
            preserved=change.preserves or (change.rationale if change.impact=='clarification' else '')
            if not challenged and not preserved.strip():
                raise ValueError('Explain preserved propositions once in preserves, or name concrete challenges: '+key+' / '+id)
            if not challenged and change.impact=='meaning' and key in candidates[id].question.fact_ids:
                raise ValueError('A corrected principal Fact needs a specific challenge; descriptive wording uses clarification: '+key)
            effects[id].append({'object_id':key,'status':'challenged' if challenged else 'preserved',
                'reason':challenged or preserved,'source_ids':change.source_ids})
    return delta,effects


def require_basis(state,question,spec=None,focus=(),candidate_id=None):
    """Resolve historical IDs in their recorded map, with attributed intervening edits."""
    spec=spec or load(state)
    if spec is None:raise ValueError('Save the referenced Behavior/Fact map first')
    version=question.audit_spec_version if question else None
    if version is None:raise ValueError('Question needs its accepted audit_spec_version')
    if version==spec.version:
        validate_question(spec,question,focus)
        return
    owner=next((c for c in state.question_candidates if c.id==candidate_id),None)
    if owner is None:raise ValueError('New questions must use the current map; historical bases require their saved Candidate')
    if not any(all(getattr(question,k)==getattr(saved,k) for k in QUESTION_BASIS) for saved in [owner.question,*owner.history]):
        raise ValueError('A changed proposition must use the current map, not reinterpret a historical basis')
    folder=Path(state.audit_spec_path).parent if state.audit_spec_path else None
    if not folder or version>state.audit_spec_version:raise ValueError('Question map version does not name an accepted basis')
    prior=ConsensusAuditSpec.model_validate_json((folder/f'v{version}.json').read_text())
    validate_question(prior,question,focus)
    for number in range(version+1,spec.version+1):
        current=spec if number==spec.version else ConsensusAuditSpec.model_validate_json((folder/f'v{number}.json').read_text())
        record=next((s for s in state.selections if s.get('map_updated') and s.get('accepted_versions',{}).get('audit_spec')==number),None)
        if not record or record.get('map_delta')!=map_delta(prior,current) or candidate_id not in record.get('map_effects',{}):
            raise ValueError('Historical map basis has an unattributed change: v'+str(number))
        for effect in record['map_effects'][candidate_id]:
            if effect['status']=='challenged' and not any(i.review_id==record['operation_id'] and i.target_id==candidate_id for i in state.review_issues):
                raise ValueError('Challenged historical basis is missing its retained review issue')
        prior=current


def record_challenges(state, before, effects, operation_id):
    """Keep new knowledge and its pending interpretation issues in the same transaction."""
    from consensus_assurance.core.types import ReviewIssue
    for id,items in effects.items():
        challenged=[item for item in items if item['status']=='challenged']
        if not challenged:continue
        candidate=next(c for c in before.question_candidates if c.id==id)
        state.review_issues.append(ReviewIssue(review_id=operation_id,target_id=id,
            target_version=candidate.question.audit_spec_version,aspect='applicability',
            source_ids=sorted({source for item in challenged for source in item['source_ids']}),
            explanation='; '.join(item['object_id']+': '+item['reason'] for item in challenged),
            disposition='investigation',reason='New implementation knowledge challenges the retained proposition; original observations remain unchanged'))


def validate_units(state,spec=None,focus=()):
    candidates={c.id:c for c in state.question_candidates}
    if sum(c.status=='active' for c in candidates.values())>1:raise ValueError('Only one active Candidate is allowed')
    owners=[u.candidate_id for u in state.units if u.status!='revised']
    if len(owners)!=len(set(owners)):raise ValueError('A Candidate has one current Unit; use independent check/model scenarios or an explicit scoped successor')
    for unit in state.units:
        if unit.status=='revised':continue
        c=candidates.get(unit.candidate_id)
        if c is None or c.obligation_id not in unit.obligation_ids:raise ValueError('Executable Unit needs its accepted Candidate and obligation: '+unit.id)
        require_basis(state,unit.audit_question,spec,focus,unit.candidate_id)
        if any(getattr(unit.audit_question,k)!=getattr(c.question,k) for k in QUESTION_BASIS):
            raise ValueError('Unit and Candidate need an explicit shared question reconnection: '+unit.id)


def reachability_refs(question):
    return set(sum((getattr(question,k) for k in REFS),[])) if question else set()


def audit_progress(state):
    spec=load(state)
    if spec is None:return []
    return [{'class_id':audit_object_key(a),'applicability':a.applicability,'obligation_ids':list(dict.fromkeys(id for u in state.units if u.audit_question and a.class_id in u.audit_question.activity_classes for id in u.obligation_ids)),
        'evidence_ids':[e.id for e in state.evidence if any(u.audit_question and a.class_id in u.audit_question.activity_classes and e.claim_id in u.obligation_ids for u in state.units)],'unknowns':a.unknowns} for a in spec.activities]
