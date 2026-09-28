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


@pytest.mark.parametrize('fault',['no_map','empty_refs','missing_fact','wrong_version','unrelated_behavior','labels_only','overview_refs','overview_usable_with_gap'])
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
        if fault.startswith('overview_'):
            spec['core_overview']=dict(status='incomplete' if fault=='overview_refs' else 'usable',
                rationale='Unfinished initial explanation',core_gaps=['Unread context transition'],formation={'fact_ids':['absent']})
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


@pytest.mark.parametrize('separate_update',[False,True])
def test_continuation_accepts_sourced_answer_but_not_rewording(tmp_path,separate_update):
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
        if separate_update:
            sub['feedback']['question_updates']={sub['candidate_id']:dict(unknowns=sub['question']['unknowns'],resume_conditions=[])}
            sub['question']['unknowns']=state['question_candidates'][0]['question']['unknowns']
        return sub,files
    e,repo=engine_for(tmp_path,[question_step,reword,progress,stop])
    (repo/'consumer.py').write_text('def consume(value):\n    return value\n')
    state=e.start(repo)
    assert len(state.question_candidates)==1 and any(q.unknowns==['Consumer unexamined'] for q in state.question_candidates[0].history)
    assert state.question_candidates[0].question.question==products()[0]['question']['question']
    assert len(diagnostics(e))==1 and 'wording' in str(diagnostics(e))
    assert 'consumer forwards' in state.question_candidates[0].question.unknowns[0]


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
    assert report.index('候选 `')<report.index('## 日志、原稿与恢复记录')


def test_fact_correction_is_saved_before_an_explicit_semantic_revision(tmp_path):
    def revise(state,authorized=False):
        from consensus_assurance.core.types import Analysis
        from consensus_assurance.core.proposals import UnitDraft,GraphPatch
        from consensus_assurance.workflow.mutations import write_set
        saved=Analysis.model_validate(state)
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['facts'][0]['meaning']='The returned value is within the independently stated local capacity'
        changes={'result':dict(impact='meaning',rationale='Distinguish the contract-bound result from mere delivery',source_ids=['doc','code'],
            challenges={state['question_candidates'][0]['id']:'The map confused observed delivery with the independently required bound; inspect the earlier attribution'})}
        sub=dict(action='research',map_path='map.json',map_changes=changes,rationale=changes['result']['rationale'],feedback=feedback(state))
        sub['feedback']['understanding']='updated'
        files={'map.json':json.dumps(spec)}
        if authorized:
            unit=saved.units[0]
            draft=UnitDraft(**{k:v for k,v in unit.model_dump().items() if k in UnitDraft.model_fields})
            draft.audit_question.audit_spec_version=state['audit_spec_version']
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
        assert state['audit_spec_version']==2 and state['units'][0]['version']==1
        assert state['review_issues'] and not state['monitor_results'][0]['reviewed_complete']
        return revise(state,True)
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),revise,accepted,stop])
    state=e.start(repo)
    assert not diagnostics(e),diagnostics(e)
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
        if not any(b['id']=='consume' for b in spec['behaviors']):spec['behaviors'].append(dict(id='consume',primary_activity='A1',execution_owner='consumer',
            protocol_context='one request',trigger='return received',consumes_fact_ids=['result'],source_ids=['consumer']))
        binding=BindingDraft(id='consumer-binding',material_id='consumer',symbol='consume',start_line=1,end_line=2,
            associations=[dict(claim_id='bounded',source_ids=['consumer'],rationale='Uses this exact local return')],
            description='Actual dependent consumer',pending=['No distributed consequence check'])
        draft=UnitDraft(**{k:v for k,v in old.model_dump().items() if k in UnitDraft.model_fields})
        draft.binding_ids.append(binding.id)
        draft.audit_question.audit_spec_version=state['audit_spec_version']
        draft.audit_question.behavior_ids.append('consume');draft.audit_question.source_ids.append('consumer')
        patch=GraphPatch(bindings=[binding],units=[draft],expected_versions={old.id:old.version},rationale='Include actual consumer without changing the principal Fact or normative claim')
        update=from_patch(saved,old,patch)
        update.source_ids=list(dict.fromkeys(update.source_ids+['consumer']))
        update.assessment=dict(decision='refinement',source_ids=update.source_ids,addressed_fields=['audit_question'],
            preserved_question=old.audit_question.question,rationale='Reconnect a known result to its actual consumer; the local bound remains unchanged',remaining_unknowns=['Distributed consequences'])
        sub=dict(action='research',map_path='map.json',scope_path='scope.json',rationale=patch.rationale,
            map_changes={'consume':dict(impact='dependency',source_ids=['consumer'],rationale='Register the actual read-only consumer',
                preserves='The prior return bound is unchanged; the accompanying explicit scope update elects to check its consumption')},
            sources=[dict(id='consumer',file='consumer.py',start_line=1,end_line=2,kind='code_observation')])
        return sub,{'map.json':json.dumps(spec),'scope.json':update.model_dump_json()}
    def knowledge_only(state):
        sub,files=expand(state);sub.pop('scope_path');files.pop('scope.json')
        return sub,files
    def elect_scope(state):
        assert state['audit_spec_version']==2 and not state['revisions']
        assert state['units'][0]['audit_question']['behavior_ids']==['call']
        return expand(state)
    e,repo=engine_for(tmp_path,[first,knowledge_only,elect_scope,check_step(),review_step(),stop])
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
            map_changes={'result':dict(impact='meaning',source_ids=['code'],rationale='Correct the bounded lifetime before deriving either obligation',
                challenges={c['id']:'Reassess the question against the corrected return lifetime' for c in state['question_candidates']})},
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


@pytest.mark.parametrize('fork',[False,True])
@pytest.mark.parametrize('failure',['grounding','format'])
def test_unaccepted_draft_pause_does_not_penalize_shared_fact_or_parent(tmp_path,fork,failure):
    def invalid(state):
        sub=products()[0]
        sub['obligation']['grounding']['applicability']=''
        sub['question']['question']='Does another consumer interpret the same result differently?'
        if failure=='format':sub['action']='invalid'
        if state['selections'][-1]['action']=='rejected':sub['repair_of']=state['selections'][-1]['operation_id']
        return sub,{}
    def independent(state):
        assert len(state['question_candidates'])==1
        assert state['question_candidates'][0]['stagnation']==0
        assert state['selections'][-1]['draft_status']=='paused'
        sub=products()[0];sub.update(action='continue',obligation=None,bindings=[])
        sub['question']['question']='Does the consumer retain the source boundary after return?'
        if fork:
            sub['parent_candidate_id']=state['question_candidates'][0]['id']
            sub['result_implications']={k:'This local answer leaves the parent obligation unresolved' for k in ['holds','violated','incomplete']}
        return sub,{}
    e,repo=engine_for(tmp_path,[first,invalid,invalid,independent,local_stop('insufficient_basis','family'),stop])
    e.config.budget.repair_attempts=2
    state=e.start(repo)
    assert len(state.question_candidates)==2 and len(diagnostics(e))==2
    before,after=state.question_candidates
    assert before.question.fact_ids==after.question.fact_ids and before.question.contexts==after.question.contexts
    assert before.stagnation==after.stagnation==0 and state.units[0].remaining_obligation_ids
    assert before.stop_reason!=after.stop_reason
    assert state.usage['agent_calls']==6 and state.usage['audit_units']==1
    draft=view(state)['drafts'][0]
    assert draft['draft_status']=='paused' and not draft['candidate_ids']


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


def instance_products():
    source = '''def create(eligible):
    return dict(eligible=set(eligible), context=None, support={}, decision=None)

def change(instance, context):
    if context is None or context == instance['context']:
        return False
    instance['context'], instance['support'] = context, {}
    return True

def support(instance, context, member, value):
    if context != instance['context'] or member not in instance['eligible']:
        return False
    instance['support'][member] = value
    if set(instance['support']) != instance['eligible'] or set(instance['support'].values()) != {value}:
        return False
    if instance['decision'] is None:
        instance['decision'] = value
    return instance['decision'] == value

def read(instance):
    return instance['decision']
'''
    spec=partial_map()
    spec['target_profile']=dict(system_boundary='Synthetic per-instance support; callers and crashes outside',
        protocol_contexts=['Independent instance context'],source_ids=['code'])
    spec['activities']=[dict(class_id=a,applicability='applicable',purpose=p,realization_summary=r,source_ids=['code'])
        for a,p,r in [('A1','Form an instance decision','Collect matching support from configured identities'),
            ('A2','Change per-instance context','Discard pending support; preserve the decision'),
            ('A4','Configure eligible identities','The caller supplies a set at instance creation'),
            ('A5','Consume the decision','read exposes the stored decision')]]
    spec['behaviors']=[dict(id=id,primary_activity=a,execution_owner='Instance caller',protocol_context='One instance',
        trigger=trigger,produces_fact_ids=produces,consumes_fact_ids=consumes,source_ids=['code'])
        for id,a,trigger,produces,consumes in [('call','A1','support call',['result'],['context']),
            ('change','A2','change call',['context'],[]),('init','A4','create call',[],[]),
            ('read','A5','read call',[],['result'])]]
    spec['facts']=[dict(id=id,meaning=meaning,identity={'instance':'Selected object'},validity_context=context,
        representation=[representation],durability='Volatile',recovery='Not implemented in this source',
        source_ids=['code'],unknowns=unknowns)
        for id,meaning,context,representation,unknowns in [
            ('result','First decision established by all configured matching support','Preserved across change','decision',[]),
            ('context','Active per-instance context after change','Until next change','context',['Caller authorization is outside the source'])]]
    spec['surfaces']=[dict(entry_point='read',disposition='deferred',source_ids=['code'],
        reason='Caller timing and completion contract need investigation; preserve this early lead')]
    def path(text,bs,fs):return dict(explanation=text,behavior_ids=bs,fact_ids=fs,source_ids=['code'])
    spec['core_overview']=dict(status='usable',rationale='The finite in-memory paths and their connection are explained; caller policy remains open',
        formation=path('support rejects stale or ineligible input, records one value per member, requires all eligible members to agree, preserves the first decision; read exposes it',['call','init','read'],['result','context']),
        context=path('create leaves context unset; change accepts a distinct non-null context, resets support, preserves decision and rejects redundant change',['init','change'],['context']),
        connection=path('support requires the current context; change invalidates pending support while the established decision survives and constrains later return',['call','change'],['result','context']),
        core_gaps=[],open_details=['Retry policy of unavailable external callers'])
    return source,spec


@pytest.mark.parametrize('combined',[False,True])
def test_default_overview_precedes_focus_without_requiring_both_labels_per_question(tmp_path,combined):
    import copy
    source,complete=instance_products()
    partial=copy.deepcopy(complete)
    partial['activities'][1]['realization_summary']='Only initial unset context read so far'
    partial['behaviors']=[b for b in partial['behaviors'] if b['id']!='change']
    partial['behaviors'][0]['consumes_fact_ids']=[]
    partial['facts']=partial['facts'][:1]
    partial['core_overview']=dict(status='incomplete',rationale='Initial state does not explain context acquisition or old work',
        core_gaps=['Read context acquisition, invalidation and stale support handling'])
    citations=products()[0]['sources'];citations[0]['end_line']=len(source.splitlines())
    def mapping(spec,changes=None):
        return dict(action='research',map_path='map.json',sources=citations,map_changes=changes or {},
            rationale='Recover sourced core understanding'),{'map.json':json.dumps(spec)}
    def question(state):
        sub=products()[0];sub.update(action='continue',obligation=None,bindings=[],sources=citations)
        sub['question'].update(question='Can support for a new context replace an established decision?',
            importance='Instance decision consistency',disposition='needs_specific_evidence',audit_spec_version=None,
            contexts=['One instance'],event_paths=['create -> change -> support -> read'],
            trigger_rationale='Compare preserved decision with subsequent actual support',unknowns=['Examine repeated caller invocations'])
        return sub,{}
    def recover(state):
        assert not state['question_candidates'] and not state['units']
        assert state['native_current']['phase']=='rejected'
        changes={id:dict(impact='dependency',rationale='Read the context transition and actual consumption',source_ids=['code']) for id in ['A2','call','core_overview']}
        sub,files=mapping(complete,changes)
        if combined:
            q,_=question(state);sub.update(q);sub['map_changes']=changes;sub['map_path']='map.json'
        return sub,files
    steps=[lambda state:mapping(partial),question,recover]+([] if combined else [question])+[stop]
    e,repo=engine_for(tmp_path,steps);e.config.directed_question=None if combined else ' ';e.config.activity_focus=['A1']
    (repo/'target.py').write_text(source)
    (repo/'README.md').write_text('Synthetic per-instance support; this fixture is not a proof of a consensus algorithm.\n')
    state=e.start(repo)
    assert len(diagnostics(e))==1 and 'Initial core understanding is incomplete' in str(diagnostics(e))
    assert len(state.question_candidates)==1 and state.question_candidates[0].question.activity_classes==['A1']
    projected=view(state)
    assert projected['understanding_status']=='usable' and projected['next_objective']['action']=='investigate_and_refocus'
    assert projected['core_overview']['open_details'] and projected['frontier']['surfaces'][0]['entry_point']=='read'
    assert not state.units and not state.evidence and state.audit_spec_version==2
    from consensus_assurance.reporting.chinese import render_report
    render_report(state,e.root)
    assert '共识形成与推进' in (e.root/'report.md').read_text()
    # Check the described small source directly; scripted descriptions do not test LLM understanding.
    namespace={};exec(source,namespace)
    instance=namespace['create']({'x','y'})
    assert namespace['change'](instance,'alpha')
    assert not namespace['support'](instance,'alpha','x',7)
    assert namespace['support'](instance,'alpha','y',7)
    assert namespace['change'](instance,'beta') and not instance['support']
    assert not namespace['support'](instance,'alpha','x',8) and namespace['read'](instance)==7


def test_initial_source_block_keeps_partial_map_and_stops_without_fabricated_candidate(tmp_path):
    spec=partial_map()
    spec['core_overview']=dict(status='blocked',rationale='Context owner source is outside the authorized snapshot',
        core_gaps=['Unavailable context owner'],open_details=['Consumer variants'])
    e,repo=engine_for(tmp_path,[map_step(spec),stop]);e.config.directed_question=None
    state=e.start(repo)
    assert not diagnostics(e) and not state.question_candidates
    assert view(state)['next_objective']['action']=='recover_core_understanding'
    from consensus_assurance.reporting.chinese import render_report
    render_report(state,e.root)
    assert '双主线初始理解尚未完成' in (e.root/'report.md').read_text()


def test_independent_construction_diagnostics_are_batched_and_repairs_make_progress(tmp_path):
    def attempt(stage):
        def step(state):
            assert not state['question_candidates'] and not state['units']
            sub,files=first(state);spec=json.loads(files['map.json'])
            if stage<1:spec['behaviors'][0]['source_ids']=['unread']
            if stage<2:spec['activities']=[]
            if stage<3:sub['obligation']['grounding']['applicability']=''
            if state['selections']:sub['repair_of']=state['selections'][-1]['operation_id']
            files['map.json']=json.dumps(spec)
            return sub,files
        return step
    e,repo=engine_for(tmp_path,[attempt(i) for i in range(4)]+[stop]);e.config.budget.repair_attempts=2
    state=e.start(repo)
    rejected=[s for s in state.selections if s['action']=='rejected']
    assert len(rejected)==3 and all(s['repeats']==1 and s['draft_status']=='active' for s in rejected)
    assert len({s['draft_id'] for s in rejected})==1 and not view(state)['drafts']
    assert all(text in rejected[0]['rationale'] for text in ['Unacquired source','Activity','grounding.applicability is empty'])
    assert 'grounding.derivation is empty' not in rejected[0]['rationale']
    assert len(state.units)==len(state.question_candidates)==1 and state.usage['agent_calls']==5


def test_execution_feedback_updates_current_unknowns_then_explanation_and_new_direction(tmp_path):
    def initial(state):
        sub,files=first(state);sub['question']['unknowns']=['The direct check has not executed']
        return sub,files
    def explained(state):
        first_candidate,selected=state['question_candidates']
        assert first_candidate['question']['unknowns']==['The direct check has not executed']
        assert first_candidate['resume_conditions']!=first_candidate['question']['unknowns']
        q=selected['question'];q.update(disposition='explained_by_existing_mechanism',unknowns=[],
            counterevidence=['The capacity branch handles the selected input'])
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['facts'][0]['unknowns']=['External consumer behavior remains outside the inspected return function']
        check=next(c for c in state['checks'] if c['action']=='direct_check')
        fb=dict(ref_ids=[check['id'],'code'],answered='The isolated invocation executed and review completed; the source bounds the return',
            remaining=['External consumer behavior'],understanding='updated',rationale='Return to the independent consumer boundary',
            question_updates={first_candidate['id']:dict(unknowns=['Distributed consequences are untested'],
                resume_conditions=['Acquire an actual consumer and its applicable contract'])})
        return dict(action='explained',candidate_id=selected['id'],question=q,feedback=fb,map_path='map.json',
            map_changes={'result':dict(impact='clarification',rationale='Separate the observed local return from an unread external consumer',source_ids=['code'])},
            rationale='Source explains the local branch; compare a third consumer question'),{'map.json':json.dumps(spec)}
    def third(state):
        sub,_=next_question(state)
        sub['question'].update(question='Which caller enforces the input precondition?',audit_spec_version=None)
        return sub,{}
    e,repo=engine_for(tmp_path,[initial,check_step(),review_step(),next_question,explained,third,stop])
    state=e.start(repo)
    assert not diagnostics(e),diagnostics(e)
    assert len(state.question_candidates)==3 and state.question_candidates[1].status=='explained'
    current=state.question_candidates[0]
    assert current.question.unknowns==['Distributed consequences are untested']
    assert any(q.unknowns==['The direct check has not executed'] for q in current.history)
    projected=view(state)
    assert projected['candidates'][0]['executions'][0]['status']=='completed'
    assert state.audit_spec_version==2 and state.usage['experiments']==1 and state.units[0].status=='checked'
    from consensus_assurance.reporting.chinese import render_report
    render_report(state,e.root)
    assert state.units[0].id in (e.root/'report.md').read_text()


def record_map(state, refined=False, challenge=False):
    spec=json.loads(Path(state['audit_spec_path']).read_text())
    for item in spec['activities']:item.pop('behavior_ids',None)
    for item in spec['facts']:
        item.pop('established_by',None);item.pop('consumed_by',None)
    if challenge:
        spec['behaviors'].append(dict(id='clear',primary_activity='A2',execution_owner='caller',protocol_context='same process',
            trigger='clear records',consumes_fact_ids=['record'],source_ids=['code']))
        changes={'clear':dict(impact='dependency',source_ids=['code'],rationale='A real shared-state write was absent from the earlier record-count history',
            challenges={state['question_candidates'][1]['id']:'clear_records can run between append and count, invalidating the assumed uninterrupted observation'})}
    else:
        producer='record-write' if refined else 'call'
        if refined:
            spec['behaviors'].append(dict(id=producer,primary_activity='A1',execution_owner='caller',protocol_context='one request',
                trigger='append inside step',produces_fact_ids=['record'],source_ids=['code']))
        else:spec['behaviors'][0]['produces_fact_ids'].append('record')
        spec['behaviors'].append(dict(id='record-read',primary_activity='A2',execution_owner='caller',protocol_context='same process',
            trigger='count records',consumes_fact_ids=['record'],source_ids=['code']))
        spec['activities'].append(dict(class_id='A2',applicability='applicable',purpose='Access recorded context',
            realization_summary='count reads the shared records; return checking only depends on the local result',source_ids=['code']))
        spec['facts'].append(dict(id='record',meaning='The call appended its result to the record list',identity={'operation':'one'},
            validity_context='Until the records are cleared',representation=['records'],durability='volatile',recovery='none',source_ids=['code']))
        spec['surfaces'].append(dict(entry_point='count',disposition='mapped',behavior_ids=['record-read'],source_ids=['code'],reason='Actual record consumer'))
        changes={} if refined else {'call':dict(impact='dependency',source_ids=['code'],rationale='Register another output of the same invocation',
            preserves='The bounded return uses the local result and capacity, not record count. No requirement, admission, schedule, oracle or observation changes. The explicit local boundary excludes concurrent calls.')}
    return dict(action='research',map_path='map.json',map_changes=changes,feedback=feedback(state),
        rationale='Feed actual implementation relationships back into the current map'),{'map.json':json.dumps(spec)}


def record_obligation(state):
    sub,plan,harness=products()
    sub=json.loads(json.dumps(sub).replace('"bounded"','"recorded"').replace('"binding"','"record-binding"'))
    plan=json.loads(json.dumps(plan).replace('"bounded"','"recorded"').replace('"binding"','"record-binding"'))
    producer='record-write' if any(b['id']=='record-write' for b in json.loads(Path(state['audit_spec_path']).read_text())['behaviors']) else 'call'
    sub.update(sources=[],feedback=feedback(state))
    sub['question'].update(audit_spec_version=None,question='Does one isolated call leave one countable record?',
        fact_ids=['record'],behavior_ids=[producer,'record-read'],activity_classes=['A1','A2'],
        obligation_relation_kind='consumption',importance='The recorded result is visible to the next local reader')
    sub['obligation']['description']='One isolated call leaves one record before clearing'
    sub['bindings'][0].update(symbol='count',start_line=6,end_line=7)
    sub['obligation']['pending']=['Proposed before execution: record observation is pending']
    plan['description']='Observe count after an actual isolated invocation'
    harness=harness.replace('from target import step','from target import step, count').replace('0 <= value <= 3','count() == 1')
    return dict(action='check',candidate=sub,plan_path='plan.json',harness_path='check.py',files={'helper.py':'helper.py'},
        rationale='Check the new consumer using the newly accepted knowledge'),{
        'plan.json':json.dumps(plan),'check.py':harness,'helper.py':'def legal(value, limit):\n    return 0 <= value <= limit\n'}


@pytest.mark.parametrize('variant',['shared','refined','interference'])
def test_knowledge_growth_preserves_execution_and_supplies_the_next_check(tmp_path,variant):
    snapshots={}
    def initial(state):
        sub,files=first(state)
        sub['sources'][0]['end_line']=9
        sub['bindings'][0].update(start_line=2,end_line=5)
        spec=json.loads(files['map.json'])
        spec['behaviors'][0]['existing_protections'].append('The call also appends its local result; record consumers remain unread')
        files['map.json']=json.dumps(spec)
        return sub,files
    def enrich(state):
        snapshots['unit']=state['units'][0]
        snapshots['claim']=state['claims'][0]
        snapshots['artifact']=state['direct_checks'][0]
        snapshots['check']=next(c for c in state['checks'] if c['action']=='direct_check')
        assert state['monitor_results'][0]['reviewed_complete']
        return record_map(state,variant=='refined')
    def more(state):
        assert state['units'][0]['audit_question']['audit_spec_version']==1
        if variant=='interference':return record_map(state,challenge=True)
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['surfaces'].append(dict(entry_point='clear_records',disposition='deferred',source_ids=['code'],reason='Uninvestigated record lifetime'))
        return dict(action='research',map_path='map.json',rationale='Record a remaining boundary'),{'map.json':json.dumps(spec)}
    def resume_first(state):
        c=state['question_candidates'][0];q=dict(c['question']);q.pop('audit_spec_version')
        return dict(action='continue',candidate_id=c['id'],question=q,feedback=feedback(state),
            rationale='Return to the preserved first discriminator using its actual completed check'),{}
    def noop(state):
        spec=json.loads(Path(state['audit_spec_path']).read_text());spec['behaviors'].reverse()
        return dict(action='research',map_path='map.json',rationale='Current understanding suffices'),{'map.json':json.dumps(spec)}
    steps=[initial,check_step(),review_step(),enrich,record_obligation,review_step(),more,resume_first,noop,stop]
    e,repo=engine_for(tmp_path,steps)
    (repo/'target.py').write_text('records=[]\ndef step(value, limit):\n    result=value + 1 if value < limit else 0\n    records.append(result)\n    return result\ndef count():\n    return len(records)\ndef clear_records():\n    records.clear()\n')
    (repo/'README.md').write_text('A legal isolated call returns within capacity and appends one record before clearing.\n')
    def interrupt(key):
        if e.state.audit_spec_version==1 and key.startswith('native-') and len(e.state.semantic_reviews)==1:
            raise KeyboardInterrupt('Prepared knowledge update before adoption')
    if variant=='shared':
        e.graph_commit_hook=interrupt
        with pytest.raises(KeyboardInterrupt):e.start(repo)
        assert e.state.audit_spec_version==1
        e.graph_commit_hook=lambda key:None
        state=e.resume()
    else:state=e.start(repo)
    assert not diagnostics(e),diagnostics(e)
    assert state.audit_spec_version==3 and len(state.units)==2
    assert state.claims[0].model_dump(mode='json')==snapshots['claim']
    assert state.direct_checks[0].model_dump(mode='json')==snapshots['artifact']
    assert next(c for c in state.checks if c.id==snapshots['check']['id']).model_dump(mode='json')==snapshots['check']
    assert state.units[0].version==snapshots['unit']['version']==1 and state.units[0].status=='checked'
    assert not state.revisions and state.usage.get('revisions',0)==0 and state.usage['experiments']==2
    assert state.usage['semantic_reviews']==2
    assert state.units[1].audit_question.audit_spec_version==2 and state.units[1].audit_question.fact_ids==['record']
    current=view(state)
    assert current['frontier']['relationships'][1]['consumers']
    assert current['conclusions'][0]['disposition']=='bounded_no_violation'
    if variant=='interference':
        assert len(state.review_issues)==1 and state.review_issues[0].target_id==state.question_candidates[1].id
        assert current['conclusions'][1]['disposition']=='investigation_lead'
        assert state.monitor_results[1]['bounded_complete'] and not state.monitor_results[1]['reviewed_complete']
        assert state.units[1].status!='checked' and current['candidates'][1]['current_applicability']=='pending_review'
    else:
        assert state.units[1].status=='checked' and not state.review_issues
    from consensus_assurance.workflow.audit_spec import validate_units
    validate_units(state)
    # Recovery replays neither a second map event nor an execution.
    counts=(len(state.selections),[c.id for c in state.checks if c.action=='direct_check'],dict(state.usage))
    state=e.resume()
    assert (len(state.selections),[c.id for c in state.checks if c.action=='direct_check'],dict(state.usage))==counts


@pytest.mark.parametrize('disposition',['explained','closed'])
def test_new_knowledge_challenges_and_reviews_a_retained_source_explanation(tmp_path,disposition):
    def explain(state):
        sub,files=question_step(state)
        sub.update(action='explained')
        sub['question'].update(disposition='explained_by_existing_mechanism',counterevidence=['The capacity branch resets the return'])
        return sub,files
    def close(state):
        return dict(action='stop',scope='candidate',reason='bounded_completed',ref_ids=[state['question_candidates'][0]['id']],
            rationale='Close only the sourced local question'),{}
    def challenge(state):
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['facts'][0]['validity_context']='Only after a legal call with a positive limit'
        return dict(action='research',map_path='map.json',rationale='Make the previously implicit legal-input boundary explicit',
            map_changes={'result':dict(impact='meaning',source_ids=['code','doc'],rationale='Recover the documented input qualification',
                challenges={state['question_candidates'][0]['id']:'Check whether the old explanation assumed arbitrary input despite the documented precondition'})}),{'map.json':json.dumps(spec)}
    def resolve(state):
        c=state['question_candidates'][0];issue=state['review_issues'][0]
        assert c['status']==disposition and not issue['resolved_by']
        answer='The recorded question is explicitly one legal invocation; the documented positive-limit qualification does not change that source explanation'
        return dict(action='review',artifact_id=c['id'],review_items=[dict(target_id=c['id'],aspect='applicability',status='no_issue_found',
            source_ids=['code','doc'],rationale=answer)],resolutions=[dict(issue_id=issue['id'],source_ids=['code','doc'],rationale=answer,residual_issue_ids=[],scope_limitations=[])],rationale='Answer the specific knowledge challenge'),{}
    def invalid_review(state):
        sub,files=resolve(state);sub['review_items'][0]['source_ids']=['missing']
        return sub,files
    steps=[explain]+([close] if disposition=='closed' else [])+[challenge,invalid_review,resolve,stop]
    e,repo=engine_for(tmp_path,steps);state=e.start(repo)
    assert len(diagnostics(e))==1 and 'review_unknown_source' in str(diagnostics(e))
    assert state.audit_spec_version==2 and state.question_candidates[0].status==disposition
    assert state.review_issues[0].resolved_by and not state.direct_checks
    assert view(state)['candidates'][0]['current_applicability']=='within_recorded_scope'


@pytest.mark.parametrize('fault',['dangling','unsourced','activity_loss','base_conflict','identity_reuse'])
def test_rejected_knowledge_update_cannot_leave_a_map_or_challenge(tmp_path,fault):
    def invalid(state):
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        changes={'call':dict(impact='dependency',source_ids=['code'],rationale='A proposed newly read boundary',
            challenges={state['question_candidates'][0]['id']:'Proposed concurrent access needs investigation'})}
        if fault=='dangling':spec['behaviors'][0]['produces_fact_ids'].append('absent')
        elif fault=='unsourced':spec['behaviors'][0]['source_ids']=[]
        elif fault=='activity_loss':spec['activities'][0]['realization_summary']='Unrelated new topic overwrites the existing summary'
        elif fault=='base_conflict':spec['version']=2
        else:
            spec['behaviors'][0]['id']='result';spec['behaviors'][0]['produces_fact_ids']=['call']
            spec['facts'][0]['id']='call';spec['facts'][0].pop('established_by')
            spec['activities'][0].pop('behavior_ids')
            changes['result']=changes['call']
        return dict(action='research',map_path='map.json',map_changes=changes,rationale='Submit a complete proposed update'),{'map.json':json.dumps(spec)}
    e,repo=engine_for(tmp_path,[first,invalid,stop]);state=e.start(repo)
    assert len(diagnostics(e))==1 and state.audit_spec_version==1 and not state.review_issues
    assert len(list((e.root/'audit-spec').glob('v*.json')))==1
    assert len(state.units)==1 and not state.revisions


def test_removed_historical_id_is_resolved_in_its_original_map(tmp_path):
    def replace(state):
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        fact=spec['facts'][0];fact['id']='delivered';fact.pop('established_by')
        spec['behaviors'][0]['produces_fact_ids']=['delivered']
        explanation=dict(impact='dependency',source_ids=['code'],rationale='Refine the recorded delivery identity while retaining the original version',
            challenges={state['question_candidates'][0]['id']:'Review the earlier delivery identity against the corrected name and boundary'})
        return dict(action='research',map_path='map.json',map_changes={'result':explanation,'call':explanation},rationale=explanation['rationale']),{'map.json':json.dumps(spec)}
    e,repo=engine_for(tmp_path,[first,check_step(),review_step(),replace,stop]);state=e.start(repo)
    assert not diagnostics(e),diagnostics(e)
    from consensus_assurance.workflow.audit_spec import validate_units
    validate_units(state)
    assert state.units[0].audit_question.fact_ids==['result'] and state.units[0].audit_question.audit_spec_version==1
    assert state.audit_spec_version==2 and not state.revisions and state.review_issues
    assert state.monitor_results[0]['bounded_complete'] and not state.monitor_results[0]['reviewed_complete']
