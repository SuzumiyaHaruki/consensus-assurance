"""Accepted research relationships through the native loop, with actual local Python tools."""
import json
from pathlib import Path
import pytest
from consensus_assurance.workflow.research import view
from native_support import first, partial_map, products, engine_for, check_step, review_step, stop, feedback


def diagnostics(engine):
    return [json.loads(p.read_text()) for p in (engine.root/'native-submissions').glob('*/diagnostics.json')]


def map_step(spec):
    return lambda state:(dict(action='research',map_path='map.json',sources=products()[0]['sources'],
        rationale='Register sourced partial understanding'),{'map.json':json.dumps(spec)})


def question_step(state):
    sub,files=first(state)
    sub.update(action='continue',obligation=None,bindings=[])
    sub['question'].update(disposition='needs_specific_evidence',unknowns=['Consumer unexamined'])
    return sub,files


@pytest.mark.parametrize('fault',['no_map','empty_refs','missing_fact','wrong_version','unrelated_behavior','labels_only'])
def test_candidate_basis_rejection_retains_whole_draft(tmp_path,fault):
    def invalid(state):
        sub,files=first(state)
        spec=json.loads(files['map.json'])
        if fault=='no_map':sub.pop('map_path')
        if fault=='empty_refs':sub['question'].update(behavior_ids=[],fact_ids=[])
        if fault=='missing_fact':sub['question']['fact_ids']=['absent']
        if fault=='wrong_version':sub['question']['audit_spec_version']=99
        if fault=='unrelated_behavior':
            spec['behaviors'].append(dict(id='unrelated',primary_activity='A1',execution_owner='other',protocol_context='another request',trigger='wake',source_ids=['code']))
            sub['question']['behavior_ids']=['unrelated']
        if fault=='labels_only':sub['question']['activity_classes']=['A1','A2']
        files['map.json']=json.dumps(spec)
        return sub,files
    e,repo=engine_for(tmp_path,[invalid,first,stop])
    state=e.start(repo)
    rejected=diagnostics(e)
    assert len(rejected)==1 and Path(rejected[0]['raw_path']).is_file()
    assert len(state.question_candidates)==len(state.units)==1
    assert state.usage['audit_units']==1 and not state.evidence


def test_unmapped_surface_explore_then_partial_map_combined_atomicity(tmp_path):
    spec=partial_map();spec.update(activities=[],behaviors=[],facts=[],surfaces=[dict(
        entry_point='target.py:step',disposition='deferred',source_ids=['code'],reason='Actual return relationship not yet understood')])
    def explore(state):
        return dict(action='explore',question='Observe the actual return without a property claim',harness_path='probe.py',rationale='Local pre-candidate exploration'),{'probe.py':'from target import step\nprint(step(3,3))\n'}
    def combined(state,bad=False):
        sub,files=first(state)
        mapping=partial_map();mapping['surfaces']=spec['surfaces']
        files['map.json']=json.dumps(mapping)
        _,plan,harness=products()
        if bad:plan['claim_id']='unaccepted'
        files.update({'plan.json':json.dumps(plan),'check.py':harness,'helper.py':'def legal(v,n): return 0 <= v <= n\n'})
        return dict(action='check',candidate=sub,plan_path='plan.json',harness_path='check.py',
            files={'helper.py':'helper.py'},rationale='Accept the research chain and execute together'),files
    def corrected(state):
        assert state['audit_spec_version']==1 and not state['units'] and not state['question_candidates'] and not state['claims']
        assert not list((e.root/'direct-checks').glob('*/plan.json'))
        assert not (e.root/'audit-spec'/'v2.json').exists()
        assert not state['evidence']
        sub,files=combined(state)
        sub['candidate']['question']['audit_spec_version']=1
        return sub,files
    def broken(state):
        sub,files=combined(state,True);sub['candidate']['question']['audit_spec_version']=1
        return sub,files
    e,repo=engine_for(tmp_path,[map_step(spec),explore,broken,corrected,review_step(),stop])
    state=e.start(repo)
    assert len(diagnostics(e))==1
    assert state.units[0].status=='checked'
    assert state.audit_spec_version==2
    assert sum(c.action=='exploration' for c in state.checks)==1
    assert all(evidence.check_id!=next(c.id for c in state.checks if c.action=='exploration') for evidence in state.evidence)
    decision=next(s for s in state.selections if s['action']=='check')
    assert decision['accepted_versions']['audit_spec']==2 and decision['accepted_versions']['units'] and decision['accepted_versions']['artifacts']


def test_cross_activity_producer_connects_to_focus_without_quota(tmp_path):
    def submit(state):
        sub,files=first(state);spec=partial_map()
        spec['activities'].append(dict(class_id='A6',applicability='applicable',purpose='Retain local output',realization_summary='The return is produced by this local representation',source_ids=['code']))
        spec['behaviors'][0].update(primary_activity='A6',cross_activity_effects={'A1':'The A1 consumer relies on this exact returned value; distributed consequence remains untested'})
        sub['question']['activity_classes']=['A1','A6']
        files['map.json']=json.dumps(spec)
        return sub,files
    e,repo=engine_for(tmp_path,[submit,stop]);e.config.activity_focus=['A1','A2']
    state=e.start(repo)
    assert len(state.units)==1 and not diagnostics(e)
    assert {r['activity'] for r in view(state)['frontier']['core_regions']}=={'A1','A2'}


def test_graph_cannot_create_unowned_unit_but_support_graph_is_allowed(tmp_path):
    def graph(state):
        sub=products()[0]
        patch=dict(claims=[sub['obligation']],bindings=sub['bindings'],units=[dict(id='unowned',
            obligation_ids=['bounded'],binding_ids=['binding'],scope=sub['obligation']['scope'],
            audit_question=sub['question'],rationale='Unowned executable work')],rationale='Attempt graph entry')
        return dict(action='research',graph_path='graph.json',rationale='Graph submission must not bypass Candidate'),{'graph.json':json.dumps(patch)}
    e,repo=engine_for(tmp_path,[map_step(partial_map()),graph,first,stop])
    state=e.start(repo)
    assert len(state.units)==1 and state.units[0].candidate_id==state.question_candidates[0].id
    assert len(diagnostics(e))==1 and 'Candidate' in str(diagnostics(e))


def test_continuation_accepts_sourced_answer_but_not_rewording(tmp_path):
    def reword(state):
        sub,files=question_step(state);sub['candidate_id']=state['question_candidates'][0]['id']
        sub['question']['question']='Could this bounded boundary call exceed capacity?'
        return sub,files
    def progress(state):
        sub,files=question_step(state);sub['candidate_id']=state['question_candidates'][0]['id']
        sub['sources'].append(dict(id='consumer',file='consumer.py',start_line=1,end_line=2,kind='code_observation'))
        sub['question']['source_ids'].append('consumer')
        sub['question']['unknowns']=['The consumer forwards the value unchanged; its external caller remains unexamined']
        sub['feedback']=dict(feedback(state),ref_ids=['consumer'],answered='The actual consumer source forwards the value without transformation')
        return sub,files
    e,repo=engine_for(tmp_path,[question_step,reword,progress,stop])
    (repo/'consumer.py').write_text('def consume(value):\n    return value\n')
    state=e.start(repo)
    assert len(state.question_candidates)==1 and len(state.question_candidates[0].history)==1
    assert state.question_candidates[0].question.question==products()[0]['question']['question']
    assert len(diagnostics(e))==1 and 'wording' in str(diagnostics(e))


def test_pending_feedback_does_not_block_an_independent_candidate(tmp_path):
    def pause(state):
        return dict(action='pause',candidate_id=state['question_candidates'][0]['id'],question=state['question_candidates'][0]['question'],
            rationale='Need unexamined consumer code',resume_conditions=['Read actual consumer']),{}
    e,repo=engine_for(tmp_path,[question_step,pause,first,check_step(),review_step(),stop])
    state=e.start(repo)
    assert state.question_candidates[0].status=='paused'
    assert state.units[0].status=='checked' and not diagnostics(e)
    from consensus_assurance.workflow.research import view
    assert 'feedback_due' not in view(state)



def test_unrelated_map_update_preserves_check_and_focus_stop_is_bounded(tmp_path):
    def update(state):
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['surfaces'].append(dict(entry_point='A2 authority context',disposition='deferred',source_ids=['code'],reason='Actual authority producer unexamined',high_consequence=True))
        sub=dict(action='research',map_path='map.json',rationale='Register an independent unexplored responsibility',feedback=feedback(state))
        sub['feedback']['understanding']='updated'
        return sub,{'map.json':json.dumps(spec)}
    def false_complete(state):
        sub,_=stop(state);sub.update(scope='focus',reason='bounded_completed')
        return sub,{}
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),update,false_complete,stop]);e.config.activity_focus=['A1','A2']
    state=e.start(repo)
    assert state.audit_spec_version==2 and state.units[0].audit_question.audit_spec_version==1
    assert state.units[0].status=='checked' and len(state.direct_checks)==1
    assert len(diagnostics(e))==1
    from consensus_assurance.reporting.chinese import render_report
    report=render_report(state,e.root).read_text()
    index=json.loads((e.root/'research.json').read_text())
    assert index['frontier']['surfaces'] and index['stop']['scope']=='run'
    assert 'A2' in report and '不是责任覆盖率' in report
    assert report.index('候选 `')<report.index('## 实际调用与边界')


def test_used_fact_semantics_require_atomic_f2_reconnection(tmp_path):
    def revise(state,authorized=False):
        from consensus_assurance.core.types import Analysis
        from consensus_assurance.core.proposals import UnitDraft,GraphPatch
        from consensus_assurance.workflow.mutations import write_set
        saved=Analysis.model_validate(state)
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['facts'][0]['meaning']='The returned value is within the independently stated local capacity'
        changes={'result':dict(impact='meaning',rationale='Distinguish the contract-bound result from mere delivery',source_ids=['doc','code'])}
        sub=dict(action='research',map_path='map.json',map_changes=changes,rationale=changes['result']['rationale'],feedback=feedback(state))
        sub['feedback']['understanding']='updated'
        files={'map.json':json.dumps(spec)}
        if authorized:
            unit=saved.units[0]
            draft=UnitDraft(**{k:v for k,v in unit.model_dump().items() if k in UnitDraft.model_fields})
            draft.audit_question.audit_spec_version=1
            patch=GraphPatch(units=[draft],expected_versions={unit.id:unit.version},rationale=sub['rationale'])
            writes=write_set(saved,patch)
            fb=dict(kind='F2',rationale=sub['rationale'],evidence_ids=['code','doc'],target_ids=[unit.id],relation_ids=[],
                new_basis='The acquired contract applies only to admitted inputs; reconnect the scoped question explicitly',
                old_judgment='Only delivery is described',new_judgment='The local contract-bound return is described',
                patch=patch.model_dump(mode='json'),grounding=products()[0]['obligation']['grounding'],
                changes=[dict(target_id=id,field=k,old_value_json=json.dumps(a),new_value_json=json.dumps(b)) for (id,k),(a,b) in writes.items()])
            sub.update(action='semantic_revision',unit_id=unit.id,feedback_path='feedback.json')
            files['feedback.json']=json.dumps(fb)
        return sub,files
    def accepted(state):
        assert state['audit_spec_version']==1 and state['units'][0]['version']==1
        return revise(state,True)
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),revise,accepted,stop])
    state=e.start(repo)
    assert len(diagnostics(e))==1,diagnostics(e)
    assert state.audit_spec_version==2 and state.units[0].version==2
    assert state.question_candidates[0].question.audit_spec_version==2
    assert state.units[0].remaining_obligation_ids==['bounded']
    assert all(not r['confirmed'] for r in state.monitor_results)
    assert state.checks and next(c for c in state.checks if c.direct_check_id).exit_code==0
    assert state.graph_history and (e.root/'audit-spec'/'v1.json').exists()


def test_explained_is_not_execution_evidence_and_forced_stop_needs_no_map(tmp_path):
    def explained(state):
        sub,files=question_step(state)
        sub.update(action='explained')
        sub['question'].update(disposition='explained_by_existing_mechanism',counterevidence=['The capacity branch resets the returned value to zero'])
        return sub,files
    e,repo=engine_for(tmp_path,[explained,stop])
    state=e.start(repo)
    assert state.question_candidates[0].status=='explained' and not state.evidence and not state.units
    other=tmp_path/'forced';other.mkdir()
    e,repo=engine_for(other,[lambda state:(dict(action='stop',scope='run',reason='user_stop',rationale='User withdrew authorization'),{})])
    state=e.start(repo)
    from consensus_assurance.reporting.chinese import render_report
    text=render_report(state,e.root).read_text()
    assert '理解尚未登记' in text and not state.audit_spec_path and not diagnostics(e)


def test_scope_reconnects_added_fact_dependency_and_keeps_old_scope(tmp_path):
    def expand(state):
        from consensus_assurance.core.types import Analysis
        from consensus_assurance.core.proposals import UnitDraft,GraphPatch,BindingDraft
        from consensus_assurance.workflow.scope_updates import from_patch
        saved=Analysis.model_validate(state);old=saved.units[0]
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        # Reverse indexes are derived from authoritative Behavior edges in the submitted file.
        spec['facts'][0].pop('consumed_by')
        spec['activities'][0].pop('behavior_ids')
        spec['behaviors'].append(dict(id='consume',primary_activity='A1',execution_owner='consumer',
            protocol_context='one request',trigger='return received',consumes_fact_ids=['result'],source_ids=['consumer']))
        binding=BindingDraft(id='consumer-binding',material_id='consumer',symbol='consume',start_line=1,end_line=2,
            associations=[dict(claim_id='bounded',source_ids=['consumer'],rationale='Uses this exact local return')],
            description='Actual dependent consumer',pending=['No distributed consequence check'])
        draft=UnitDraft(**{k:v for k,v in old.model_dump().items() if k in UnitDraft.model_fields})
        draft.binding_ids.append(binding.id)
        draft.audit_question.audit_spec_version=1
        draft.audit_question.behavior_ids.append('consume');draft.audit_question.source_ids.append('consumer')
        patch=GraphPatch(bindings=[binding],units=[draft],expected_versions={old.id:old.version},rationale='Include actual consumer without changing the principal Fact or normative claim')
        update=from_patch(saved,old,patch)
        update.source_ids=list(dict.fromkeys(update.source_ids+['consumer']))
        update.assessment=dict(decision='refinement',source_ids=update.source_ids,addressed_fields=['audit_question'],
            preserved_question=old.audit_question.question,rationale='Reconnect a known result to its actual consumer; the local bound remains unchanged',remaining_unknowns=['Distributed consequences'])
        sub=dict(action='research',map_path='map.json',scope_path='scope.json',rationale=patch.rationale,
            sources=[dict(id='consumer',file='consumer.py',start_line=1,end_line=2,kind='code_observation')])
        return sub,{'map.json':json.dumps(spec),'scope.json':update.model_dump_json()}
    e,repo=engine_for(tmp_path,[first,expand,check_step(),review_step(),stop])
    (repo/'consumer.py').write_text('def consume(value):\n    return value\n')
    state=e.start(repo)
    assert not diagnostics(e),diagnostics(e)
    assert state.audit_spec_version==2 and len(state.units)==2
    assert state.units[1].status=='revised' and state.units[0].status=='checked'
    assert state.units[0].audit_question.behavior_ids==['call','consume']
    assert state.units[1].audit_question.audit_spec_version==1
    assert state.revisions[-1].kind=='F3'


def test_descriptive_noop_and_removal_are_explicit_without_reexecution(tmp_path):
    def clarify(state,remove=False):
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['facts'][0]['meaning']='The invocation has delivered its local return value'
        changes={'result':dict(impact='clarification',source_ids=['code'],rationale='Same delivery semantics and identity, more precise local wording')}
        if remove:
            spec['facts'][0]['unknowns']=[]
            changes={}
        return dict(action='research',map_path='map.json',map_changes=changes,rationale='Refine sourced wording'),{'map.json':json.dumps(spec)}
    def noop(state):
        return dict(action='research',map_path='map.json',rationale='Confirm current map already suffices'),{'map.json':Path(state['audit_spec_path']).read_text()}
    e,repo=engine_for(tmp_path,[first,clarify,noop,lambda s:clarify(s,True),stop])
    state=e.start(repo)
    assert state.audit_spec_version==2 and len(diagnostics(e))==1
    assert len(list((e.root/'audit-spec').glob('v*.json')))==2
    assert state.units[0].audit_question.audit_spec_version==1


def test_review_can_supply_feedback_without_an_extra_turn(tmp_path):
    def review(state):
        sub,_=review_step()(state)
        sub['feedback']=feedback(state)
        sub['feedback']['ref_ids'].append(state['direct_checks'][-1]['id'])
        return sub,{}
    def finish(state):
        from consensus_assurance.core.types import Analysis
        assert "feedback_due" not in state
        sub,_=stop(state);sub.pop('feedback')
        return sub,{}
    e,repo=engine_for(tmp_path,[first,check_step(),review,finish])
    state=e.start(repo)
    assert not diagnostics(e) and state.units[0].status=='checked'


def test_map_transaction_recovery_has_one_version_and_unit(tmp_path):
    e,repo=engine_for(tmp_path,[first])
    def interrupt(key):raise KeyboardInterrupt('Prepared graph transaction before adoption')
    e.graph_commit_hook=interrupt
    with pytest.raises(KeyboardInterrupt):e.start(repo)
    assert not e.state.units and e.state.usage['agent_calls']==1
    e.graph_commit_hook=lambda key:None
    state=e.resume()
    assert state.audit_spec_version==1 and len(state.units)==1 and state.usage['audit_units']==1
    assert len(list((e.root/'audit-spec').glob('v*.json')))==1


def test_shared_fact_can_reconnect_paused_and_active_candidates_atomically(tmp_path):
    def pause(state):
        return dict(action='pause',candidate_id=state['question_candidates'][0]['id'],question=state['question_candidates'][0]['question'],
            rationale='Inspect another discriminator first',resume_conditions=['Return after independent source reading']),{}
    def other(state):
        sub,files=question_step(state);sub['question']['question']='Which consumer uses this return?'
        sub['feedback']=feedback(state)
        return sub,files
    def reconnect(state):
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['facts'][0]['validity_context']='The return value remains associated with this one completed call'
        questions={c['id']:{**c['question'],'audit_spec_version':1} for c in state['question_candidates']}
        return dict(action='research',map_path='map.json',reconnect_questions=questions,
            map_changes={'result':dict(impact='meaning',source_ids=['code'],rationale='Clarify the bounded lifetime before deriving either obligation')},
            rationale='Reconnect both sourced hypotheses to the revised Fact without changing their status'),{'map.json':json.dumps(spec)}
    e,repo=engine_for(tmp_path,[question_step,pause,other,reconnect,stop])
    state=e.start(repo)
    assert not diagnostics(e),diagnostics(e)
    assert state.audit_spec_version==2 and [c.status for c in state.question_candidates]==['paused','active']
    assert all(c.question.audit_spec_version==2 and c.history for c in state.question_candidates)


def next_question(state):
    sub=products()[0]
    sub.update(action='continue',obligation=None,bindings=[])
    sub['question'].update(contexts=['Another sourced invocation'],
        disposition='needs_specific_evidence',unknowns=['Inspect the other invocation boundary'])
    return sub,{}


def local_stop(reason='bounded_completed', scope='candidate'):
    def step(state):
        candidate=state['question_candidates'][-1]
        return dict(action='stop',scope=scope,reason=reason,ref_ids=[candidate['id']],
            rationale='The scoped discriminator is disposed; compare other sourced directions',
            frontier_comparison='Other invocation contexts remain available in the mapped region',
            resume_conditions=[] if reason=='bounded_completed' else ['Acquire the missing producer observation'],
            feedback=feedback(state)),{}
    return step


@pytest.mark.parametrize('disposition',['bounded','confirmed','explained'])
def test_local_disposition_continues_with_mapped_unknowns(tmp_path,disposition):
    def initial(state):
        sub,files=first(state)
        if disposition=='explained':
            sub.update(action='explained',obligation=None,bindings=[])
            sub['question'].update(disposition='explained_by_existing_mechanism',unknowns=[],
                counterevidence=['The source branch bounds the return'])
        return sub,files
    steps=[initial]+([] if disposition=='explained' else [check_step(),review_step()])
    steps += [local_stop(),next_question,stop]
    e,repo=engine_for(tmp_path,steps)
    if disposition=='confirmed':
        (repo/'target.py').write_text('def step(value, limit):\n    return value + 1\n')
        # Actual isolated execution with scripted products, never autonomous discovery.
        e.agent.mock=False
        e.config.execution_isolation='bwrap'
        e.config.directed_question='Controlled small-target confirmation regression'
    state=e.start(repo)
    assert len(state.question_candidates)==2 and not diagnostics(e)
    assert state.question_candidates[0].status=='closed'
    assert state.native_session_id=='fixture-session' and state.usage['agent_calls']==len(steps)
    research=view(state)
    assert research['frontier']['relationships'][0]['unknowns']==['Consumer outside boundary']
    assert state.audit_spec_version==1 and state.run_stop['scope']=='run'
    if disposition=='confirmed':
        result=research['conclusions'][0]
        assert result['disposition']=='confirmed_in_scope' and result['concern']=='implementation_semantics'
        assert 'distributed consequences' in result['scope']['excluded']


def test_conditional_input_continues_to_actual_producer_in_the_same_history(tmp_path):
    def initial(state):
        sub,files=first(state)
        sub['sources'].append(dict(id='producer-source',file='target.py',start_line=3,end_line=4,kind='code_observation'))
        sub['question']['source_ids'].append('producer-source')
        sub['question']['supporting_behavior_ids']={'produce':'The actual input producer supplies the call whose return is checked'}
        sub['question']['activity_classes'].append('A7')
        spec=json.loads(files['map.json'])
        spec['activities'].append(dict(class_id='A7',applicability='applicable',purpose='Admit a public input',
            realization_summary='The actual producer bounds a requested value',source_ids=['producer-source']))
        spec['behaviors'].append(dict(id='produce',primary_activity='A7',execution_owner='caller',
            protocol_context='one request',trigger='produce input',produces_fact_ids=['input'],source_ids=['producer-source']))
        spec['behaviors'][0]['consumes_fact_ids']=['input']
        spec['facts'].append(dict(id='input',meaning='The producer returned the bounded input',identity={'operation':'one'},
            validity_context='one invocation',representation=['return'],durability='volatile',recovery='none',source_ids=['producer-source']))
        files['map.json']=json.dumps(spec)
        sub['bindings'].append(dict(id='producer-binding',material_id='producer-source',symbol='produce',start_line=3,end_line=4,
            associations=[dict(claim_id='bounded',source_ids=['producer-source'],rationale='Actual input of the selected call')],
            description='The allowed input producer',pending=[]))
        return sub,files
    def check(actual=False):
        def submit(state):
            sub,files=check_step(revise=actual)(state)
            plan=json.loads(files['plan.json'])
            plan['binding_ids'].append('producer-binding')
            plan['harness']['prerequisites'].append(dict(alias='producer',event='produced'))
            plan['harness']['prerequisites'][0]['conditions'].append(dict(field='state.value',reference='producer.state.value'))
            files['plan.json']=json.dumps(plan)
            files['check.py']='''import json
from target import step, produce
def emit(event, **state):
    print('CA_EVENT '+json.dumps(dict(event=event,operation='one',state=state)))
'''+('value,limit=produce(9)\nemit("produced",value=value)\n' if actual else 'value,limit=3,3\n')+'''
emit('admitted',legal=0<=value<=limit,value=value)
returned=step(value,limit)
emit('returned',in_range=0<=returned<=limit)
'''
            return sub,files
        return submit
    def review(state):
        sub,files=review_step()(state)
        sub['review_items'][0]['source_ids'].append('producer-source')
        return sub,files
    e,repo=engine_for(tmp_path,[initial,check(),check(True),review,stop])
    with (repo/'target.py').open('a') as stream:stream.write('def produce(request):\n    return min(3, max(0, request)), 3\n')
    state=e.start(repo)
    assert not list((e.root/'native-submissions').glob('*/diagnostics.json')),state.native_current
    assert len(state.direct_checks)==2 and len(state.question_candidates)==1
    old,new=state.monitor_results
    assert old['outcome']=='unknown' and new['outcome']=='holds'
    assert new['properties'][0]['comparison_complete'] and not new['confirmed']
    assert state.units[0].status=='checked' and state.audit_spec_version==1


def test_rejected_local_family_yields_without_erasing_budget_or_issue(tmp_path):
    invalid=lambda state:({'action':'invalid','rationale':'Unusable draft'}, {})
    def renamed(state):
        sub=products()[0];sub.update(action='continue',obligation=None,bindings=[])
        return sub,{}
    e,repo=engine_for(tmp_path,[first,invalid,invalid,renamed,next_question,stop])
    e.config.budget.repair_attempts=2
    state=e.start(repo)
    assert len(state.question_candidates)==2,state.native_current
    assert state.question_candidates[0].status=='paused' and state.question_candidates[0].stagnation==2
    assert state.units[0].remaining_obligation_ids
    assert state.usage['agent_calls']==6 and state.usage['audit_units']==1
    errors=[json.loads(p.read_text()) for p in (e.root/'native-submissions').glob('*/diagnostics.json')]
    assert len(errors)==3 and any('cannot reset' in str(d) for d in errors)


@pytest.mark.parametrize('unavailable',['budget','backend'])
def test_exhausted_execution_capacity_allows_source_research_but_no_placeholder_unit(tmp_path,unavailable):
    def source_only(state):
        sub,files=first(state);sub.update(action='continue',obligation=None,bindings=[])
        sub['question'].update(disposition='needs_specific_evidence',unknowns=['No authorized execution remains'])
        return sub,files
    e,repo=engine_for(tmp_path,[first,source_only,stop])
    if unavailable=='budget':e.config.budget.experiments=0
    else:e.config.execution_backend='none';e.implementation=None
    state=e.start(repo)
    assert not state.units and not state.claims
    assert len(state.question_candidates)==1 and not view(state)['capacity']['new_obligation']
    assert state.usage['agent_calls']==3


@pytest.mark.parametrize('scope',['candidate','family','focus'])
def test_local_tool_gap_preserves_unit_and_continues(scope,tmp_path):
    e,repo=engine_for(tmp_path,[first,local_stop('tool_gap',scope),next_question,stop])
    state=e.start(repo)
    assert len(state.question_candidates)==2 and state.question_candidates[0].status=='paused'
    assert state.units[0].remaining_obligation_ids and state.usage['agent_calls']==4
    assert state.run_stop['scope']=='run'


def test_local_handoff_recovers_without_reexecuting_checked_work(tmp_path):
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),local_stop(),next_question,stop])
    original=e.checkpoint
    interrupted=False
    def checkpoint(event):
        nonlocal interrupted
        original(event)
        if event=='native_execution_completed' and e.state.native_current.get('scope')=='candidate' and not interrupted:
            interrupted=True
            raise KeyboardInterrupt('Controlled interruption after durable local handoff')
    e.checkpoint=checkpoint
    with pytest.raises(KeyboardInterrupt):e.start(repo)
    e.checkpoint=original
    state=e.resume()
    assert len(state.question_candidates)==2
    assert state.usage['experiments']==1 and state.usage['agent_calls']==6
    assert len([s for s in state.selections if s['action']=='stop' and s['scope']=='candidate'])==1
