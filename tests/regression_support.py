"""Small product and source constructors for bounded local regressions."""
def declared_changes(state, feedback):
    """Construct explicit changes in controlled fixtures; production never fills missing declarations."""
    import json
    from consensus_assurance.workflow.mutations import write_set
    from consensus_assurance.core.proposals import JudgmentChange
    feedback.changes=[JudgmentChange(target_id=id,field=field,old_value_json=json.dumps(before),new_value_json=json.dumps(after)) for (id,field),(before,after) in write_set(state,feedback.patch).items()]
    return feedback


def toy_responses(repo):
    """Instantiate the synthetic whole-document citation against the copied fixture.

    Fixed code intervals remain intentional test inputs. This does not migrate
    archived runs or normalize real backend responses.
    """
    import json
    from pathlib import Path
    responses=json.loads((Path(__file__).parent/'fixtures/toy_responses.json').read_text())
    request=next(r for r in responses['reads'] if r['file']=='README.md')
    old_id=f"README.md:{request['start_line']}:{request['end_line']}"
    request['end_line']=len((Path(repo)/'README.md').read_text().splitlines())
    new_id=f"README.md:1:{request['end_line']}"
    def replace(value):
        if isinstance(value,str):return new_id if value==old_id else value
        if isinstance(value,list):return [replace(v) for v in value]
        if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
        return value
    return replace(responses)


def add_dependency(state,responses):
    from consensus_assurance.core.types import Relation
    edge=Relation(id='input_dependency',source='step_obligation',target='input_obligation',kind='boundary',group=None,
        rationale='The checked consumer depends on actual producer input',pending=['Producer guarantee remains unverified'],grounding=state.claims[1].grounding.model_copy(deep=True))
    if not state.relations:state.relations.append(edge)
    from consensus_assurance.core.proposals import RelationDraft
    responses['graph']['relations']=[{k:v for k,v in edge.model_dump(mode='json').items() if k in RelationDraft.model_fields}]
    state.units[0].relation_ids=['input_dependency'];responses['graph']['units'][0]['relation_ids']=['input_dependency']


def read_material(repo, snapshot, file, start_line, end_line):
    from consensus_assurance.core.types import Material
    path=repo/file
    text="\n".join(path.read_text().splitlines()[start_line-1:end_line])
    return Material(id=f"{file}:{start_line}:{end_line}",file=file,
        start_line=start_line,end_line=end_line,text=text,
        kind='document_statement' if path.suffix=='.md' else 'code_observation',
        content_digest=snapshot.files[file])


def add_reads(state,repo,requests):
    additions=[read_material(repo,state.snapshot,**{k:r[k] for k in ('file','start_line','end_line')}) for r in requests]
    known={m.id for m in state.materials}
    state.materials.extend(m for m in additions if m.id not in known)
    return [m.id for m in additions]


def revision_for(state, ids):
    import json
    from consensus_assurance.core.proposals import ClaimDraft, GraphPatch, Feedback, JudgmentChange
    drafts=[];changes=[]
    for id in ids:
        old=next(c for c in state.claims if c.id==id)
        new=ClaimDraft(**{k:v for k,v in old.model_dump().items() if k in ClaimDraft.model_fields})
        new.description=old.description+' with a weaker requirement'
        drafts.append(new)
        changes.append(JudgmentChange(target_id=id,field='description',old_value_json=json.dumps(old.description),new_value_json=json.dumps(new.description)))
    basis=drafts[0].grounding.model_copy(deep=True);basis.unresolved=[];basis.conflicts=[]
    return Feedback(kind='F2',rationale='Candidate correction',evidence_ids=basis.expectation_ids or basis.source_ids,target_ids=[ids[0]],relation_ids=[],new_basis='Actual materials support the requested correction',patch=GraphPatch(claims=drafts,expected_versions={i:1 for i in ids},rationale='Correction'),changes=changes,old_judgment=state.claims[1].description,new_judgment=drafts[0].description,grounding=basis)


def dependency(dependency_prepared):
    from consensus_assurance.core.proposals import GraphPatch, BindingDraft, RelationDraft, UnitDraft
    from consensus_assurance.adapters.storage.snapshot import capture
    repo, state, _ = dependency_prepared
    (repo/'new_helper.py').write_text('def boundary(value):\n    return max(1, value)\n')
    state.snapshot=capture(repo)
    added=add_reads(state,repo,[{'file':'new_helper.py','start_line':1,'end_line':2,'reason':'Read a previously absent provider'}])
    u=state.units[0];basis=state.relations[0].grounding.model_copy(deep=True)
    b=BindingDraft(id='fresh_provider',associations=[dict(claim_id=u.obligation_ids[0],source_ids=[added[0]],rationale='Selected fixture operation')],material_id=added[0],symbol='boundary',start_line=1,end_line=2,description='New supporting producer',pending=['Guarantee not checked'])
    edge=RelationDraft(id='fresh_dependency',source=u.obligation_ids[0],target=b.id,kind='boundary',group=None,rationale='The selected computation consumes the actual provider',pending=['Provider guarantee unverified'],grounding=basis)
    draft=UnitDraft(**{k:v for k,v in u.model_dump().items() if k in UnitDraft.model_fields})
    draft.binding_ids.append(b.id);draft.relation_ids.append(edge.id)
    return state,GraphPatch(bindings=[b],relations=[edge],units=[draft],expected_versions={u.id:u.version},rationale='Reconnect newly read producer'),added


def setup(tmp_path,prepared,broken=False):
    import shutil
    from consensus_assurance.core.types import Grounding, AuditQuestion
    from consensus_assurance.core.proposals import ObservableProperty, Comparison, EventMonitor, DirectCheckPlan, Harness, EventRequirement
    from consensus_assurance.core.config import Config
    from consensus_assurance.registry import assemble
    from consensus_assurance.workflow.engine import Engine, FRAMEWORK_REVISION
    from consensus_assurance.workflow.budget import BudgetTracker
    from consensus_assurance.adapters.storage.snapshot import capture
    repo, state, _ = prepared
    if broken:(repo/'counter.py').write_text((repo/'counter.py').read_text().replace('return value + 1 if value < limit else 0','return value + 1'))
    state.snapshot=capture(repo);state.mode='real';state.analysis_mode='regression';state.framework_revision=FRAMEWORK_REVISION
    for i,m in enumerate(state.materials):
        if m.file=='counter.py':
            state.materials[i]=read_material(repo,state.snapshot,file=m.file, start_line=1, end_line=len((repo/m.file).read_text().splitlines()))
            state.materials[i].id=m.id
    for binding in state.bindings:
        binding.snapshot_id=state.snapshot.id;binding.content_digest=state.snapshot.files[binding.file]
        binding.excerpt='\n'.join((repo/binding.file).read_text().splitlines()[binding.start_line-1:binding.end_line])
    unit=state.units[0];unit.binding_ids=['step_binding']
    unit.scope.excluded.append('Cluster-wide consequences outside this finite call')
    basis=Grounding(source_ids=['counter.py:1:10'],expectation_ids=[next(m.id for m in state.materials if m.file=='README.md')],binding_ids=unit.binding_ids,derivation='Finite legal counter inputs must return within capacity',applicability='One local operation, legal initial value and positive capacity')
    for claim in state.claims:
        claim.pending=[];claim.grounding=basis.model_copy(deep=True)
    unit.audit_question=AuditQuestion(question='Does one legal boundary call preserve the range?',importance='Bounded service result',source_ids=basis.source_ids+basis.expectation_ids,
        disposition='ready_for_check',preferred_check='direct_test',event_paths=['legal input -> actual call -> correlated observed return'],trigger_rationale='Observe actual return and independent range predicate')
    cfg=Config(execution_backend='python',allow_experiments=True,allow_agent_materials=True,execution_isolation='workspace')
    state.config=cfg.model_dump(mode='json')
    e=Engine(cfg,tmp_path/'direct',*assemble(cfg));e.state=state;e.budget=BudgetTracker(cfg.budget,state)
    shutil.copytree(repo,e.root/'source');state.active_unit_id=unit.id
    source='''import json
from counter import step
value, limit = 3, 3
def emit(event, **values):
    print('CA_EVENT ' + json.dumps({'event': event, 'operation': 'one', 'participant': 'local', 'context': 'configured', 'state': values}))
emit('admitted', value=value, limit=limit, input_valid=0 <= value <= limit and limit > 0)
returned = step(value, limit)
emit('returned', value=returned, in_range=0 <= returned <= limit)
'''
    identities=['operation','participant','context']
    prop=ObservableProperty(checker_id='Range',trigger=Comparison(field='event',value='returned'),assertion=Comparison(field='state.in_range',value=True),identity_fields=identities,description='Observed result remains in the documented capacity range')
    monitor=EventMonitor(id='range',checker_id='Range',event='returned',
        binding_ids=unit.binding_ids,grounding=basis,admission_alias='start')
    plan=DirectCheckPlan(description='One actual boundary call',claim_id=unit.obligation_ids[0],binding_ids=unit.binding_ids,
        harness=Harness(kind='python',source=source,description='Actual fixture call and independent bound observation',semantic_changes=['Emit actual event values after the target call'],legality=basis,
            prerequisites=[EventRequirement(alias='start',event='admitted',conditions=[Comparison(field='state.input_valid',value=True)])]),
        monitors=[monitor],observable_properties=[prop])
    return e,unit,plan


def review(state,unit,artifact):
    from consensus_assurance.workflow.review_contract import target_contract
    from consensus_assurance.core.types import SemanticReview, SemanticCheck
    # Explicit controlled semantic input; real execution is tested separately.
    contract=target_contract(state,artifact)
    state.semantic_reviews.append(SemanticReview(task_id='controlled',check_id='controlled',target_versions={artifact.id:artifact.version},
        material_ids=contract['required_material_ids'],items=[SemanticCheck(target_id=artifact.id,aspect='checker_correspondence',status='no_issue_found',source_ids=contract['required_material_ids'],rationale='The fixture contract, actual call, prerequisites and independent oracle agree within the supplied local scope')],origin='mock'))
