"""Actual fixture execution, never a real backend or a production correctness claim."""
import json
import shutil
import pytest
from consensus_assurance.core.types import *
from consensus_assurance.core.proposals import *
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine,FRAMEWORK_REVISION
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.workflow.direct_checks import save_plan,execute,assess,validate_plan,proceed
from consensus_assurance.workflow.review_contract import target_contract
from consensus_assurance.adapters.runners.experiment import extract_events
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.workflow.materials import read_material


def setup(tmp_path,prepared,broken=False):
    repo,state,_,_=prepared
    if broken:(repo/'counter.py').write_text((repo/'counter.py').read_text().replace('return value + 1 if value < limit else 0','return value + 1'))
    state.snapshot=capture(repo);state.mode='real';state.analysis_mode='regression';state.framework_revision=FRAMEWORK_REVISION
    for i,m in enumerate(state.materials):
        if m.file=='counter.py':
            state.materials[i]=read_material(repo,state.snapshot,ReadRequest(file=m.file,start_line=1,end_line=len((repo/m.file).read_text().splitlines()),reason='Actual fixture source'))
            state.materials[i].id=m.id
    state.file_index={}
    for binding in state.bindings:
        binding.snapshot_id=state.snapshot.id;binding.content_digest=state.snapshot.files[binding.file]
        binding.excerpt='\n'.join((repo/binding.file).read_text().splitlines()[binding.start_line-1:binding.end_line])
    unit=state.units[0];unit.binding_ids=['step_binding']
    basis=Grounding(source_ids=['counter.py:1:10'],expectation_ids=[next(m.id for m in state.materials if m.file=='README.md')],binding_ids=unit.binding_ids,derivation='Finite legal counter inputs must return within capacity',applicability='One local operation, legal initial value and positive capacity')
    for claim in state.claims:
        claim.pending=[];claim.grounding=basis.model_copy(deep=True)
    unit.audit_question=AuditQuestion(question='Does one legal boundary call preserve the range?',importance='Bounded service result',source_ids=basis.source_ids+basis.expectation_ids,
        disposition='ready_for_check',preferred_check='direct_test',event_paths=['legal input -> actual call -> correlated observed return'],trigger_rationale='Observe actual return and independent range predicate')
    cfg=Config(execution_backend='python',allow_experiments=True,allow_agent_materials=True,execution_isolation='workspace')
    state.config=cfg.model_dump(mode='json')
    e=Engine(cfg,tmp_path/'direct',*assemble(cfg),'');e.state=state;e.budget=BudgetTracker(cfg.budget,state)
    shutil.copytree(repo,e.root/'source');state.active_unit_id=unit.id
    source='''import json
from counter import step
value, limit = 3, 3
metadata = {'legal': 0 <= value <= limit and limit > 0}
def emit(event, **values):
    print('CA_EVENT ' + json.dumps({'event': event, 'operation': 'one', 'participant': 'local', 'context': 'configured', 'metadata': metadata, 'state': values}))
emit('admitted', value=value, limit=limit)
returned = step(value, limit)
emit('returned', value=returned, in_range=0 <= returned <= limit)
'''
    identities=['operation','participant','context']
    prop=ObservableProperty(checker_id='Range',trigger=Comparison(field='metadata.legal',value=True),assertion=Comparison(field='state.in_range',value=True),identity_fields=identities,description='Observed result remains in the documented capacity range')
    monitor=EventMonitor(id='range',checker_id='Range',event='returned',
        binding_ids=unit.binding_ids,grounding=basis,applicability_conditions=[prop.trigger])
    plan=DirectCheckPlan(description='One actual boundary call',claim_id=unit.obligation_ids[0],scope=unit.scope,binding_ids=unit.binding_ids,
        harness=Harness(kind='python',source=source,description='Actual fixture call and independent bound observation',prerequisite_events=['admitted','returned'],semantic_changes=[],legality=basis,legal_conditions=[prop.trigger],
            prerequisites=[EventRequirement(alias='start',event='admitted'),EventRequirement(alias='end',event='returned',conditions=[Comparison(field=k,reference='start.'+k) for k in identities])]),
        monitors=[monitor],observable_properties=[prop])
    return e,unit,plan


def review(state,unit,artifact):
    # Explicit controlled semantic input; real execution is tested separately.
    contract=target_contract(state,artifact)
    state.semantic_reviews.append(SemanticReview(task_id='controlled',check_id='controlled',target_versions={artifact.id:artifact.version},context_dependencies={artifact.id:contract},
        material_ids=contract['required_material_ids'],items=[SemanticCheck(target_id=artifact.id,aspect='checker_correspondence',status='no_issue_found',source_ids=contract['required_material_ids'],rationale='The fixture contract, actual call, prerequisites and independent oracle agree within the supplied local scope')],origin='mock'))


@pytest.mark.parametrize('broken',[False,True])
def test_actual_direct_result_without_model(tmp_path,prepared,broken):
    from consensus_assurance.adapters.agents.backend import MockAgent
    from consensus_assurance.workflow.inquiry import process_task,review_unit
    e,u,p=setup(tmp_path,prepared,broken);validate_plan(e.state,u,p,e.implementation)
    review_unit(e,u,'before_check');assert not e.state.inquiry_tasks
    a=save_plan(e,u,p,'generation');e.state.active_direct_check_id=a.id
    proceed(e,u,'direct_execute')
    assert e.state.monitor_results[-1]['outcome']==('violated' if broken else 'holds')
    assert not e.state.monitor_results[-1]['confirmed']
    assert len(e.state.inquiry_tasks)==1 and e.state.inquiry_tasks[0].target_ids==[a.id]
    contract=target_contract(e.state,a)
    e.agent=MockAgent();e.agent.responses=[ReviewReply(items=[SemanticCheck(target_id=a.id,aspect='checker_correspondence',status='no_issue_found',source_ids=contract['required_material_ids'],rationale='The selected contract applies to this legal local call; correlated returns and the independent range comparison implement it. Network and durability are outside this check.')],limitations=[]).model_dump(mode='json')]
    process_task(e,e.state.inquiry_tasks[0])
    c=next(c for c in e.state.checks if c.action=='direct_check')
    result=assess(e.state,u,a,p,c,extract_events(c))
    assert target_contract(e.state,a)['object_type']=='direct_check'
    assert not e.state.models and c.direct_check_id==a.id and c.model_id is None
    assert result['confirmed']==broken,result
    assert result['outcome']==('violated' if broken else 'holds'),result
    assert e.state.evidence[-1].level=='implementation_test'
    assert all(claim.assessment==Assessment.UNASSESSED for claim in e.state.claims)
    if broken:
        assert e.state.findings[-1].level=='implementation_obligation'
        assert e.state.findings[-1].direct_check_id==a.id
    assert len(e.state.semantic_reviews)==1 and e.state.inquiry_tasks[0].status=='completed'


@pytest.mark.parametrize('failure',['prerequisite','missing','compile','instrumentation','disputed','unreviewed','identity','applicability'])
def test_direct_failure_never_confirms(tmp_path,prepared,failure):
    e,u,p=setup(tmp_path,prepared,True)
    if failure=='prerequisite':p.harness.prerequisites[0].event='not_observed'
    if failure=='missing':p.harness.source=p.harness.source.replace('in_range=0 <= returned <= limit','other=0 <= returned <= limit')
    if failure=='compile':p.harness.source+='\ninvalid python syntax!'
    if failure=='instrumentation':p.harness.semantic_changes=['Alter protocol behavior to produce the outcome']
    if failure=='identity':p.harness.source=p.harness.source.replace("'operation': 'one'", "'operation': event")
    if failure=='applicability':p.monitors[0].applicability_conditions=[Comparison(field='metadata.unknown',value=True)]
    a=save_plan(e,u,p,'negative')
    if failure!='unreviewed':review(e.state,u,a)
    if failure=='disputed':e.state.semantic_reviews[0].items[0].status='disputed'
    c=execute(e,a);result=assess(e.state,u,a,p,c,extract_events(c))
    assert not result['confirmed'],result
    assert result['outcome']==('unknown' if failure in {'prerequisite','missing','compile','identity'} else 'violated'),result
    assert not any(f.level=='implementation_obligation' for f in e.state.findings)


def test_controlled_schedule_has_typed_model_fallback(tmp_path,prepared):
    e,u,p=setup(tmp_path,prepared);u.audit_question.preferred_check='controlled_schedule'
    e.ask=lambda *args,**kwargs:(DirectCheckReply(gap='Adapter has no deterministic pause point; sleep is insufficient',fallback='local_model'),CheckRun(action='agent',cwd=str(e.root),snapshot_id=e.state.snapshot.id))
    proceed(e,u,'direct_check')
    assert e.state.next_action=='build' and not e.state.direct_checks and not e.state.models
    from consensus_assurance.workflow.artifacts import save_bundle
    from consensus_assurance.workflow.inquiry import review_unit
    model=save_bundle(e.root,e.state,u,prepared[2],e.implementation)
    review_unit(e,u,'after_search',model)
    assert any(model.id in t.target_ids for t in e.state.inquiry_tasks)


@pytest.mark.parametrize('refine',[False,True])
def test_descriptive_derivation_reaches_actual_direct_execution(tmp_path,prepared,refine):
    from consensus_assurance.core.proposals import Discovery
    from test_audit_capabilities import inventory
    from consensus_assurance.adapters.agents.backend import MockAgent
    from consensus_assurance.adapters.storage.files import write_json
    e,u,plan=setup(tmp_path,prepared);responses=prepared[3]
    spec=inventory('counter.py:1:10')
    initial=spec.model_copy(deep=True)
    if refine:initial.behaviors[0].produces_fact_ids=['missing']
    derivation=GraphDraft.model_validate(responses[1]);derivation.units[0].audit_question=u.audit_question
    q=derivation.units[0].audit_question;q.activity_classes=['A1','A5'];q.behavior_ids=['producer','consumer'];q.fact_ids=['fact'];q.obligation_relation_kind='consumption'
    replies=[responses[0],Discovery(understanding='Controlled descriptive input',audit_spec=initial).model_dump(mode='json')]
    if refine:replies.append(SpecRefinement(understanding='Separate the established input from the unknown producer',delta=AuditSpecDelta(behaviors=[spec.behaviors[0]],rationale='Restore the sourced producer edge'),limitations=['Unverified durability remains explicit']).model_dump(mode='json'))
    replies.extend([derivation.model_dump(mode='json'),DirectCheckReply(plan=plan,gap='').model_dump(mode='json')])
    fixture=tmp_path/'direct-responses.json';write_json(fixture,replies)
    config=e.config.model_copy(deep=True);config.agent_backend='mock';config.fixture=str(fixture);config.budget.semantic_reviews=0
    class StopAfterActualCheck(Engine):
        def record(self,check):
            super().record(check)
            if check.action=='direct_check':raise RuntimeError('Stop after actual direct execution receipt')
    impl,_,verifier,knowledge=assemble(config)
    engine=StopAfterActualCheck(config,tmp_path/'whole',impl,MockAgent(fixture),verifier,knowledge,'')
    with pytest.raises(RuntimeError,match='actual direct'):engine.start(prepared[0])
    assert engine.state.usage['agent_calls']==5+int(refine)
    assert not engine.state.models and not engine.state.repair_sessions
    assert all(t.status=='completed' for t in engine.state.inquiry_tasks if t.kind=='spec_refine')
    assert sum(t.kind=='spec_refine' for t in engine.state.inquiry_tasks)==int(refine)
    receipt=json.loads((engine.root/'actions'/engine.state.pending_action.id/'result.json').read_text())
    assert receipt['action']=='direct_check' and receipt['exit_code']==0


def test_exact_selected_reads_then_one_focused_continuation(tmp_path,prepared):
    # Prepare the unread source before capturing this new fixture analysis.
    (prepared[0]/'adapter.py').write_text('owns_snapshot = True\n')
    e,u,p=setup(tmp_path,prepared)
    q=u.audit_question;q.disposition='needs_specific_evidence';q.preferred_check=None
    q.requests=[ReadRequest(file='adapter.py',start_line=1,end_line=1,reason='Selected consumer ownership discriminator')]
    e.state.next_action='question';calls=[]
    def ask(kind,response_type,context,validator=None,**kwargs):
        calls.append(kind)
        assert any(m['file']=='adapter.py' for m in context['materials'])
        answered=q.model_copy(deep=True);answered.requests=[];answered.disposition='explained_by_existing_mechanism'
        answered.source_ids.append('adapter.py:1:1');answered.trigger_rationale='The actual adapter owns the representation; this explains only the selected ownership suspicion'
        reply=QuestionReply(question=answered,explanation='Source establishes the previously missing owner')
        if validator:validator(reply)
        return reply,CheckRun(action='agent',cwd=str(e.root),snapshot_id=e.state.snapshot.id)
    e.ask=ask
    e.process_unit(u)
    assert calls==['question'] and not e.state.models and not e.state.direct_checks
    assert e.state.usage.get('exploration_rounds',0)==0
    assert next(p for p in e.state.read_plans.values() if p['original_requests'][0]['file']=='adapter.py')['purpose']=='depth'
    assert not e.state.active_unit_id and e.state.graph_history


def test_direct_violation_enters_separate_consequence_analysis(tmp_path,prepared):
    e,u,p=setup(tmp_path,prepared,True);a=save_plan(e,u,p,'consequence');review(e.state,u,a)
    execute(e,a);e.state.active_direct_check_id=a.id;e.state.next_action='direct_assess';calls=[]
    def ask(kind,response_type,context,validator=None,**kwargs):
        calls.append(kind)
        reply=ConsequenceReply(disposition='obligation_only',rationale='Only this local return is observed; wider goal consequences are unestablished',source_ids=u.audit_question.source_ids,limitations=['No correlated system-level witness'])
        if validator:validator(reply)
        return reply,CheckRun(action='agent',cwd=str(e.root),snapshot_id=e.state.snapshot.id)
    e.ask=ask;e.process_unit(u)
    assert calls==['consequence'] and e.state.consequences[0]['disposition']=='obligation_only'
    assert e.state.findings[0].level=='implementation_obligation' and not e.state.models
    from consensus_assurance.reporting.chinese import render_report
    assert '直接检查' in render_report(e.state,e.root).read_text()


def test_new_direct_artifact_does_not_hide_prior_oracle_dispute(tmp_path,prepared):
    e,u,p=setup(tmp_path,prepared,True);old=save_plan(e,u,p,'old');review(e.state,u,old)
    e.state.review_issues.append(ReviewIssue(review_id='old',target_id=old.id,target_version=1,aspect='checker_correspondence',source_ids=u.audit_question.source_ids,explanation='Oracle may use the wrong return boundary',disposition='investigation',reason='Must resolve the specific dispute'))
    new=save_plan(e,u,p,'new');review(e.state,u,new)
    c=execute(e,new);result=assess(e.state,u,new,p,c,extract_events(c))
    assert not result['confirmed'] and 'Unresolved semantic counterevidence' in result['limitations']


def test_source_continuation_uses_existing_attributed_F2(tmp_path,prepared):
    from consensus_assurance.workflow.direct_checks import continue_question
    e,u,p=setup(tmp_path,prepared);claim=next(c for c in e.state.claims if c.id==u.obligation_ids[0])
    draft=ClaimDraft(**{k:v for k,v in claim.model_dump(mode='json').items() if k in ClaimDraft.model_fields})
    draft.description+=' within the explicitly selected finite input scope'
    revision=SemanticRevision(rationale='Attribute the finite configured contract',evidence_ids=claim.source_ids,target_ids=[claim.id],new_basis='The supplied fixture defines the bounded input contract',
        patch=GraphPatch(claims=[draft],expected_versions={claim.id:claim.version},rationale='Explicit semantic refinement'),
        changes=[JudgmentChange(target_id=claim.id,field='description',old_value_json=json.dumps(claim.description),new_value_json=json.dumps(draft.description))],
        old_judgment=claim.description,new_judgment=draft.description,grounding=claim.grounding)
    def ask(kind,response_type,context,validator=None,**kwargs):
        response=QuestionReply(question=u.audit_question,explanation='Explicit F2 before another check',revision=revision)
        if validator:validator(response)
        return response,CheckRun(action='agent',cwd=str(e.root),snapshot_id=e.state.snapshot.id)
    e.ask=ask;continue_question(e,u)
    assert e.state.revisions[-1].kind=='F2' and e.state.revisions[-1].status=='applied'
    assert next(c for c in e.state.claims if c.id==claim.id).version==2
    assert e.state.next_action=='select' and not e.state.models


def test_stale_binding_cannot_ground_direct_execution(tmp_path,prepared):
    e,u,p=setup(tmp_path,prepared)
    e.state.bindings[0].snapshot_id='another_snapshot'
    with pytest.raises(ValueError,match='selected source snapshot'):
        validate_plan(e.state,u,p,e.implementation)
    assert not e.state.direct_checks and not e.state.evidence


def test_direct_F4_keeps_failed_prerequisite_and_revision_history(tmp_path,prepared):
    e,u,p=setup(tmp_path,prepared);p.harness.prerequisites[0].event='unreached'
    old=save_plan(e,u,p,'before-F4');failed=execute(e,old)
    e.state.active_direct_check_id=old.id
    proceed(e,u,'direct_assess')
    assert e.state.pending_feedback['kind']=='F4'
    fixed=p.model_copy(deep=True);fixed.harness.prerequisites[0].event='admitted'
    def ask(kind,response_type,context,validator=None,**kwargs):
        reply=DirectCheckReply(plan=fixed,gap='')
        if validator:validator(reply)
        return reply,CheckRun(action='agent',cwd=str(e.root),snapshot_id=e.state.snapshot.id)
    e.ask=ask;proceed(e,u,'direct_check')
    revision=e.state.revisions[-1]
    assert revision.kind=='F4' and revision.evidence_ids==[failed.id]
    assert revision.before['direct_check_id']==old.id and revision.after['direct_check_id']!=old.id
    assert e.state.usage['revisions']==1 and e.state.usage['replays']==1
    assert e.state.monitor_results[0]['prerequisites']['status']=='not_reached'
    assert not e.state.models and not e.state.evidence


def test_question_narrowing_preserves_structural_identity_and_counterevidence(tmp_path,prepared):
    e,u,p=setup(tmp_path,prepared)
    q=u.audit_question;q.disposition='concrete_suspicion';q.preferred_check='direct_test'
    q.activity_classes=['A6'];q.behavior_ids=['producer'];q.fact_ids=['representation'];q.obligation_relation_kind='preservation'
    q.counterevidence=['Consumer contract remains unverified'];q.unknowns=['Injected adapter applicability']
    def ask(kind,response_type,context,validator=None,**kwargs):
        narrowed=q.model_copy(deep=True);narrowed.question='Which consumer contract requires preserving this same representation?'
        narrowed.importance='Consequences depend on the same original recovery contract'
        narrowed.disposition='needs_specific_evidence';narrowed.preferred_check='source_review'
        reply=QuestionReply(question=narrowed,explanation='Narrow applicability before executing')
        validator(reply)
        wrong=reply.model_copy(deep=True);wrong.question.fact_ids=['different_fact']
        with pytest.raises(ValueError,match='structural'):validator(wrong)
        wrong=reply.model_copy(deep=True);wrong.question.counterevidence=[]
        with pytest.raises(ValueError,match='counterevidence'):validator(wrong)
        return reply,CheckRun(action='agent',cwd=str(e.root),snapshot_id=e.state.snapshot.id)
    e.ask=ask
    from consensus_assurance.workflow.direct_checks import continue_question
    continue_question(e,u)
    assert e.state.units[0].audit_question.preferred_check=='source_review'
    assert e.state.units[0].audit_question.counterevidence==q.counterevidence


def test_direct_event_comparison_uses_correlated_raw_fields(tmp_path,prepared):
    e,u,p=setup(tmp_path,prepared)
    source=p.harness.source
    source=source.replace("emit('returned', value=returned, in_range=0 <= returned <= limit)", "emit('returned', value=returned, in_range=0 <= returned <= limit, limit=limit)")
    p.harness.source=source
    p.observable_properties[0].assertion=Comparison(field='state.limit',reference='start.state.limit')
    validate_plan(e.state,u,p,e.implementation)
    a=save_plan(e,u,p,'correlated-fields')
    c=execute(e,a)
    result=assess(e.state,u,a,p,c,extract_events(c))
    assert result['properties'][0]['outcome']=='holds'
    assert result['outcome']=='holds' and not result['confirmed']  # Raw comparison survives an unreviewed conclusion.
    events=extract_events(c)
    assert next(x for x in events if x['event']=='admitted')['state']['value']==3
    assert next(x for x in events if x['event']=='returned')['state']['limit']==3
