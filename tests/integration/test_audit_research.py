"""Accepted research relationships through the audit loop, with actual local Python tools."""
import json
from pathlib import Path
import pytest
from consensus_assurance.workflow.research import view
from consensus_assurance.reporting.chinese import render_report
from audit_support import first, partial_map, products, engine_for, check_step, review_step, stop, feedback, instance_products, local_stop, next_question, question_step, diagnostics


def map_step(spec):
    return lambda state:(dict(action='research',map_path='map.json',sources=products()[0]['sources'],
        rationale='Register sourced partial understanding'),{'map.json':json.dumps(spec)})


def open_first(state):
    sub,files=first(state);spec=json.loads(files['map.json'])
    spec['behaviors'][0]['cross_activity_effects']={'A2':'Each invocation supplies fresh bounds; no prior call state is retained'}
    path=dict(explanation='One synchronous invocation establishes the return under its own input bounds; prior calls retain no state',
        behavior_ids=['call'],fact_ids=['result'],source_ids=['code'])
    spec['core_overview']=dict(status='usable',rationale='The synthetic stateless boundary is fully sourced',
        formation=path,context=path,connection=path)
    files['map.json']=json.dumps(spec)
    return sub,files


def test_candidate_basis_rejection_retains_whole_draft(tmp_path):
    def invalid(state):
        from consensus_assurance.workflow.audit import validate_submission
        import shutil
        for fault in ('no_map','empty_refs','missing_fact','wrong_version','unrelated_behavior','labels_only','overview_refs','overview_usable_with_gap'):
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
            root=tmp_path/fault;shutil.copytree(e.root,root)
            for name,text in {**files,'submission.json':json.dumps(sub)}.items():(root/'draft'/name).write_text(text)
            result=validate_submission(e.state.model_copy(deep=True),root,'submission.json',e.implementation)
            assert not result['valid'] and result['diagnostics'],fault
            assert not e.state.question_candidates and not e.state.usage.get('audit_units')
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
        spec['behaviors'].append(dict(id='prefix',primary_activity='A1',execution_owner='caller',protocol_context='initialization',trigger='start',source_ids=['code']))
        sub['question']['supporting_behavior_ids']={'prefix':'Legal initial invocation prefix; not a direct producer of the return'}
        sub['question']['activity_classes']=['A1','A6']
        files['map.json']=json.dumps(spec)
        return sub,files
    e,repo=engine_for(tmp_path,[submit,stop]);e.config.activity_focus=['A1','A2']
    state=e.start(repo)
    assert len(state.units)==1 and not diagnostics(e)
    assert state.units[0].audit_question.supporting_behavior_ids
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


def test_question_converges_before_obligation_and_results_do_not_propagate(tmp_path):
    lead='Does caller interference explain the returned value?'
    def initial(state):
        sub,files=question_step(state)
        sub['question'].update(question=lead,unknowns=['Cause has not been isolated'])
        return sub,files
    def converge(state):
        c=state['question_candidates'][0]
        q=dict(c['question']);q['question']=products()[0]['question']['question']
        return dict(action='continue',candidate_id=c['id'],question=q,
            feedback=dict(feedback(state),answered='The sourced public contract supports a direct return-bound discriminator; it does not isolate caller interference'),
            rationale='Select the observable contract before deriving its first obligation'),{}
    def combined(state):
        sub,files=first(state);sub['candidate_id']=state['question_candidates'][0]['id']
        spec=json.loads(files['map.json'])
        spec['surfaces']=[dict(entry_point='external caller',disposition='deferred',source_ids=['code'],reason='Cause attribution and external use remain unexamined')]
        files['map.json']=json.dumps(spec)
        _,plan,harness=products()
        files.update({'plan.json':json.dumps(plan),'check.py':harness,'helper.py':'def legal(v,n): return 0 <= v <= n\n'})
        sub['feedback']=dict(feedback(state),answered='The first obligation checks only the returned bound; cause and downstream consequences remain separate',
            question_updates={sub['candidate_id']:dict(unknowns=['Cause has not been isolated'],resume_conditions=[])})
        return dict(action='check',candidate=sub,plan_path='plan.json',harness_path='check.py',files={'helper.py':'helper.py'},
            rationale='Accept the aligned question, map and first actual check together'),files
    def independent(state):
        sub,_=question_step(state);sub.pop('map_path');sub['question'].pop('audit_spec_version')
        sub['question'].update(question='Does caller interference uniquely account for this return?',unknowns=['Cause has not been isolated'])
        sub['feedback']=feedback(state)
        return sub,{}
    def child(state):
        parent=state['question_candidates'][1]
        sub,_=independent(state)
        sub.update(action='explained',parent_candidate_id=parent['id'],
            result_implications={k:'Only this synchronous-call boundary is addressed; the parent cause question stays open' for k in ['holds','violated','incomplete']})
        sub['question'].update(question='Can this synchronous return read a shared variable inside step?',
            disposition='explained_by_existing_mechanism',counterevidence=['The function reads only its parameters'],unknowns=[])
        return sub,{}
    def revise_without_attribution(state):
        c=state['question_candidates'][0]
        q=dict(c['question']);q['question']='Does the caller always consume a bounded value?'
        q['audit_spec_version']=state['audit_spec_version']
        return dict(action='continue',candidate_id=c['id'],question=q,feedback=feedback(state),
            rationale='Attempt to replace an accepted obligation question without F2'),{}
    e,repo=engine_for(tmp_path,[initial,converge,combined,review_step(),independent,child,revise_without_attribution,stop])
    (repo/'target.py').write_text('def step(value, limit):\n    return value + 1\n')
    e.agent.mock=False;e.config.execution_isolation='bwrap'
    state=e.start(repo)
    assert len(diagnostics(e))==1 and 'semantic revision' in str(diagnostics(e))
    first_q,other,derived=state.question_candidates
    assert first_q.question.question==products()[0]['question']['question']
    assert any(q.question==lead for q in first_q.history)
    assert state.units[0].audit_question.question==first_q.question.question and not state.revisions
    assert state.audit_spec_version==2 and state.usage['experiments']==1
    assert first_q.question.fact_ids==other.question.fact_ids and first_q.question.contexts==other.question.contexts
    assert first_q.question.obligation_relation_kind==other.question.obligation_relation_kind
    assert first_q.parent_candidate_id is other.parent_candidate_id is None
    assert derived.parent_candidate_id==other.id and derived.status=='explained' and other.status=='paused'
    projected=view(state)
    assert projected['candidates'][0]['results'][0]['disposition']=='confirmed_in_scope'
    assert projected['candidates'][1]['results']==projected['candidates'][2]['results']==[]
    assert first_q.status=='paused' and not first_q.resume_conditions
    assert len(projected['conclusions'])==1 and projected['conclusions'][0]['candidate_id']==first_q.id
    assert other.question.unknowns==['Cause has not been isolated'] and not derived.obligation_id


@pytest.mark.usefixtures('full_refresh_equivalence')
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


def test_only_configured_directed_disposition_can_complete_a_run(tmp_path):
    def explain(state):
        sub,files=question_step(state);sub['action']='explained'
        sub['question'].update(disposition='explained_by_existing_mechanism',unknowns=[],counterevidence=['The capacity branch handles the call'])
        return sub,files
    def finish(state):
        return dict(action='stop',scope='run',reason='bounded_completed',
            ref_ids=[state['question_candidates'][0]['id']],rationale='The configured finite source question is explained'),{}
    e,repo=engine_for(tmp_path,[explain,finish]);e.config.budget.agent_calls=20
    state=e.start(repo)
    assert not diagnostics(e) and state.run_stop['origin']=='agent'
    assert state.run_stop['reason']=='bounded_completed' and state.usage['agent_calls']==2
    assert state.elapsed_seconds<e.config.budget.total_seconds


def test_directed_completion_does_not_erase_execution_or_review_debt(tmp_path):
    def explain(state):
        c=state['question_candidates'][0]
        return dict(action='explained',candidate_id=c['id'],question=dict(c['question'],
            disposition='explained_by_existing_mechanism',counterevidence=['Source branch bounds return']),
            rationale='The source explanation cannot erase the executed dispute'),{}
    def finish(state):
        return dict(action='stop',scope='run',reason='bounded_completed',
            ref_ids=[state['question_candidates'][0]['id']],rationale='Claim completion despite pending correspondence'),{}
    e,repo=engine_for(tmp_path,[first,check_step(),review_step('disputed'),explain,finish])
    state=e.start(repo)
    assert len(diagnostics(e))==1 and 'finite task is disposed' in str(diagnostics(e))
    assert {w['kind'] for w in state.run_stop['pending_work']}=={'unit','review_issue'}
    assert not state.review_issues[0].resolved_by and state.units[0].status!='checked'
    assert state.run_stop['origin']=='controller' and state.usage['agent_calls']==5
    assert view(state)['units'][0]['source_explanation'] is None
    assert state.monitor_results and state.checks and '已选检查／复核待办' in render_report(state,e.root).read_text()




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
    assert not list((e.root/'submissions').glob('*/diagnostics.json')),state.current_submission
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
    assert state.units[0].remaining_obligation_ids
    assert state.active_unit_id is None
    assert before.stop_reason!=after.stop_reason
    assert state.usage['agent_calls']==6 and state.usage['audit_units']==1
    draft=view(state)['drafts'][0]
    assert draft['draft_status']=='paused' and not draft['candidate_ids']


@pytest.mark.parametrize('unavailable',['budget','backend','units'])
def test_exhausted_execution_capacity_allows_source_research_but_no_placeholder_unit(tmp_path,unavailable):
    def source_only(state):
        sub,files=first(state);sub.update(action='continue',obligation=None,bindings=[])
        sub['question'].update(disposition='needs_specific_evidence',unknowns=['No authorized execution remains'])
        return sub,files
    def attempt_exploration(state):
        return dict(action='explore',question='Observe without a new obligation',harness_path='probe.py',
            rationale='Execution capacity is independent of Unit admission'),{'probe.py':'from target import step\nprint(step(3,3))\n'}
    e,repo=engine_for(tmp_path,[first,attempt_exploration,source_only,stop])
    if unavailable=='budget':e.config.budget.experiments=0
    elif unavailable=='units':e.config.budget.audit_units=0
    else:e.config.execution_backend='none';e.implementation=None
    state=e.start(repo)
    assert not state.units and not state.claims
    assert len(state.question_candidates)==1 and not view(state)['capacity']['new_obligation']
    assert state.usage['agent_calls']==4 and state.usage.get('experiments',0)==int(unavailable=='units')
    assert any(c.action=='exploration' for c in state.checks)==(unavailable=='units')
    assert len(diagnostics(e))==(1 if unavailable=='units' else 2)


@pytest.mark.parametrize('scope',['candidate','family','focus'])
def test_local_tool_gap_preserves_unit_and_continues(scope,tmp_path):
    e,repo=engine_for(tmp_path,[first,local_stop('tool_gap',scope),next_question,stop])
    state=e.start(repo)
    assert len(state.question_candidates)==2 and state.question_candidates[0].status=='paused'
    assert state.units[0].remaining_obligation_ids and state.usage['agent_calls']==4
    assert state.run_stop['scope']=='run'


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
        assert state['current_submission']['phase']=='rejected'
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


def test_sourced_feedback_updates_unknowns_and_preserves_history(tmp_path):
    def answer(state):
        c=state['question_candidates'][0]
        fb=dict(feedback(state),answered='The source branch bounds this local return; the external consumer remains unread',
            question_updates={c['id']:dict(unknowns=['External consumer responsibility'],resume_conditions=['Acquire the consumer contract'])})
        return dict(action='research',feedback=fb,rationale='Update only this saved question'),{}
    e,repo=engine_for(tmp_path,[question_step,local_stop('insufficient_basis'),answer,next_question,stop])
    state=e.start(repo)
    c=state.question_candidates[0]
    assert not diagnostics(e) and c.status=='paused' and len(state.question_candidates)==2
    assert c.question.unknowns==['External consumer responsibility'] and c.resume_conditions==['Acquire the consumer contract']
    assert c.history[-1].unknowns==['Consumer unexamined']
    assert not state.units and not state.evidence and state.audit_spec_version==1
    index=json.loads((e.root/'research.json').read_text())
    assert index['candidates'][0]['resume_conditions']==c.resume_conditions
    assert index['candidates'][0]['record']['match']=={'id':c.id}
    assert 'Acquire the consumer contract' in render_report(state,e.root).read_text()


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
        if not any(a['class_id']=='A2' for a in spec['activities']):
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
    basis=sub['obligation']['grounding']
    basis.update(derivation='step appends its local result; count reads the same list before any clear',
        applicability='One isolated call followed by count with no intervening clear')
    plan['harness']['legality']=basis
    plan['monitors'][0]['grounding']=basis
    plan['observable_properties'][0]['description']='The isolated invocation leaves exactly one countable record before clearing'
    sub['bindings'][0].update(symbol='count',start_line=6,end_line=7)
    sub['obligation']['pending']=['Proposed before execution: record observation is pending']
    plan['description']='Observe count after an actual isolated invocation'
    harness=harness.replace('from target import step','from target import step, count').replace('0 <= value <= 3','count() == 1')
    return dict(action='check',candidate=sub,plan_path='plan.json',harness_path='check.py',files={'helper.py':'helper.py'},
        rationale='Check the new consumer using the newly accepted knowledge'),{
        'plan.json':json.dumps(plan),'check.py':harness,'helper.py':'def legal(value, limit):\n    return 0 <= value <= limit\n'}


def recording_first(state):
    sub,files=first(state)
    sub['sources'][0]['end_line']=9
    sub['bindings'][0].update(start_line=2,end_line=5)
    spec=json.loads(files['map.json'])
    spec['behaviors'][0]['existing_protections'].append('The call also appends its local result; record consumers remain unread')
    spec['behaviors'][0]['consumes_fact_ids']=['instance']
    spec['activities'].append(dict(class_id='A2',applicability='applicable',purpose='Establish local instance context',
        realization_summary='Process initialization creates the instance; observations use this instance until shutdown',source_ids=['code']))
    spec['behaviors'].append(dict(id='start',primary_activity='A2',execution_owner='module loader',protocol_context='one process',
        trigger='initialize module',produces_fact_ids=['instance'],source_ids=['code']))
    spec['facts'].append(dict(id='instance',meaning='The fresh process owns an initialized records list',identity={'instance':'process'},
        validity_context='Until process shutdown',representation=['records'],durability='volatile',recovery='fresh process',source_ids=['code']))
    def path(text,bs,fs):return dict(explanation=text,behavior_ids=bs,fact_ids=fs,source_ids=['code'])
    spec['core_overview']=dict(status='usable',rationale='Explain the finite local result path and the fresh instance boundary',
        formation=path('step computes a local return and appends it; its caller receives that return',['call'],['result']),
        context=path('Module initialization establishes one process instance; shutdown discards its state',['start'],['instance']),
        connection=path('Calls append in their initialized process; a new process starts fresh and cannot inherit earlier results',['start','call'],['instance','result']),
        core_gaps=[],open_details=['External ordering between record consumption and clearing is not supplied'])
    files['map.json']=json.dumps(spec)
    return sub,files

@pytest.mark.parametrize('variant',['shared','refined','interference'])
@pytest.mark.usefixtures('full_refresh_equivalence')
def test_knowledge_growth_preserves_execution_and_supplies_the_next_check(tmp_path,variant):
    snapshots={}
    def initial(state):
        sub,files=recording_first(state)
        if variant=='shared':
            spec=json.loads(files['map.json'])
            spec['behaviors'][0]['unknowns']=['Does the local boundary overflow?', 'The boundary checker correspondence is pending', 'Clearing schedules remain independent']
            spec['core_overview']['open_details'].insert(0,'The boundary checker correspondence is pending')
            spec['surfaces']=[dict(entry_point='local-return',disposition='deferred',source_ids=['code'],reason='Does the local boundary overflow?')]
            files['map.json']=json.dumps(spec)
        return sub,files
    def enrich(state):
        snapshots['unit']=state['units'][0]
        snapshots['claim']=state['claims'][0]
        snapshots['artifact']=state['direct_checks'][0]
        snapshots['check']=next(c for c in state['checks'] if c['action']=='direct_check')
        snapshots['review']=state['semantic_reviews'][0]
        assert state['monitor_results'][0]['reviewed_complete']
        if variant=='shared':
            accepted=next(s for s in state['selections'] if s['operation_id']==snapshots['review']['check_id'])
            assert snapshots['artifact']['id'] in accepted['feedback']['ref_ids']
            assert snapshots['unit']['status']=='checked' and state['usage']['agent_calls']==7
        raw,files=record_map(state,variant=='refined')
        if variant=='shared':
            snapshots['map1']=(e.root/'audit-spec/v1.json').read_bytes()
            index=json.loads((e.root/'research.json').read_text())
            lead=next(h for h in index['handoffs'] if 'left one record for count' in h['answered_preview'])
            assert lead['operation_id']!=index['handoffs'][-1]['operation_id']
            ref=lead['record']
            saved=json.loads((e.root/ref['path']).read_text())
            original=next(x for x in saved[ref['collection']] if all(x[k]==v for k,v in ref['match'].items()))
            assert original['feedback']['remaining']==['Describe the consumer relation before proposing its obligation.']
            executions=index['records']
            retained=json.loads((e.root/executions['path']).read_text())
            check=next(c for c in retained['checks'] if c['id'] in original['feedback']['ref_ids'])
            assert check['action']=='exploration' and 'record count 1' in Path(check['stdout']).read_text()
            snapshots['handoff_id']=lead['operation_id']
            assert any(h['operation_id']==lead['operation_id'] and 'surface:local-return' in h['ref_ids'] for h in index['map_handoffs'])
            assert not original['map_updated'] and original['feedback']['understanding']=='updated'
            raw['feedback']['ref_ids'].append(check['id'])
            raw['feedback']['answered']='The saved exploration motivates source mapping of the record producer and consumer'
            raw['feedback']['remaining']=original['feedback']['remaining']
            spec=json.loads(files['map.json'])
            spec['behaviors'][0]['unknowns']=['Clearing schedules remain independent']
            spec['behaviors'][0]['important_branches']=['Returning the local result and retaining it in records are separate effects; clearing records does not retract an already returned value.']
            spec['core_overview']['open_details'].remove('The boundary checker correspondence is pending')
            raw['map_changes']['core_overview']=dict(impact='clarification',source_ids=['code'],
                rationale='Remove completed checker work from semantic unknowns at the consumer-map handoff',
                preserves='Execution and review remain in their exact records; no requirement, history or dependency changes')
            spec['surfaces'][0].update(disposition='mapped',behavior_ids=['call'],
                reason='The admitted boundary call takes the increment branch; its local overflow was checked. Other callers and clearing schedules remain independent.')
            raw['map_changes']['surface:local-return']=dict(impact='clarification',source_ids=['code'],
                rationale='Associate the sourced boundary entry with its actual Behavior; mapping does not close wider caller questions')
            files['map.json']=json.dumps(spec)
        return raw,files
    def more(state):
        assert state['units'][0]['audit_question']['audit_spec_version']==1
        if variant=='interference':return record_map(state,challenge=True)
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['surfaces'].append(dict(entry_point='clear_records',disposition='deferred',source_ids=['code'],reason='Uninvestigated record lifetime',high_consequence=True))
        return dict(action='research',map_path='map.json',rationale='Record a remaining boundary'),{'map.json':json.dumps(spec)}
    def next_check(state):
        assert len(state['monitor_results'])==1 and state['monitor_results'][0]['claim_id']=='bounded'
        return record_obligation(state)
    def resume_first(state):
        c=state['question_candidates'][0];q=dict(c['question']);q.pop('audit_spec_version')
        return dict(action='continue',candidate_id=c['id'],question=q,feedback=feedback(state),
            rationale='Return to the preserved first discriminator using its actual completed check'),{}
    def resolve(state):
        assert state['monitor_results'][0]['reviewed_complete'] and not state['monitor_results'][1]['reviewed_complete']
        c=state['question_candidates'][1];issue=state['review_issues'][0]
        assert issue['target_id']==c['id'] and not issue['resolved_by']
        answer='The fixed check calls step then count in one isolated process, with no clear between them; the new writer challenges other schedules, not this recorded before-clearing boundary'
        return dict(action='review',artifact_id=c['id'],review_items=[dict(target_id=c['id'],aspect='applicability',status='no_issue_found',
            source_ids=['code','doc'],rationale=answer)],resolutions=[dict(issue_id=issue['id'],source_ids=['code','doc'],
                evidence_ids=[state['direct_checks'][1]['id']],rationale=answer,residual_issue_ids=[],scope_limitations=['Schedules with an intervening clear remain unchecked'])],
            rationale='Resolve the specific interpretation against the fixed execution, without changing its requirement'),{}
    def third(state):
        if variant=='interference':
            assert state['review_issues'] and not state['review_issues'][0]['resolved_by']
            assert state['monitor_results'][0]['reviewed_complete'] and not state['monitor_results'][1]['reviewed_complete']
        sub,_=next_question(state)
        sub['sources']=[]
        sub['question'].update(question='Which caller ordering permits record clearing?',audit_spec_version=None)
        return sub,{}
    def noop(state):
        spec=json.loads(Path(state['audit_spec_path']).read_text());spec['behaviors'].reverse()
        return dict(action='research',map_path='map.json',rationale='Current understanding suffices'),{'map.json':json.dumps(spec)}
    def explore(state):
        return dict(action='explore',question='Observe a separate record consumer',harness_path='explore.py',
            rationale='Read actual local feedback without adding a claim'),{
            'explore.py':"from target import step, count\nstep(3,3)\nprint('record count', count())\n"}
    def handoff(state):
        check=next(c for c in reversed(state['checks']) if c['action']=='exploration')
        return dict(action='research',rationale='Save the small consumer observation before map work',feedback=dict(
            ref_ids=[check['id'],'code','call','surface:local-return'],answered='The actual isolated call left one record for count. This supplements the checked local return; clearing schedules remain independent.',
            remaining=['Describe the consumer relation before proposing its obligation.'],
            understanding='updated',
            rationale='Keep the observation separate from the confirmed return proposition.')),{}
    def unrelated_handoff(state):
        raw,_=handoff(state)
        raw['feedback'].update(ref_ids=['result'],answered='The separate clearing function mutates the records list without returning the earlier call result.',
            remaining=[],rationale='Retain another sourced observation; the earlier consumer lead is still independent.')
        return raw,{}
    def review_inherit(state):
        raw,files=review_step()(state)
        raw['review_items'][0].pop('target_id')
        if variant=='shared' and len(state['units'])==1:
            candidate=state['question_candidates'][0]['id']
            check=next(c['id'] for c in state['checks'] if c['action']=='direct_check')
            raw['feedback']=dict(ref_ids=[candidate,'call','surface:local-return',check,state['direct_checks'][0]['id'],'code'],
                answered='The admitted boundary reaches the increment branch and returns 4 above 3. This answers the local boundary question only.',
                remaining=['Clearing schedules remain independent'],understanding='updated',
                rationale='Retain the actual scoped result for source backfill without closing the wider consumer question')
        return raw,files
    steps=[initial,check_step(),review_inherit]
    if variant=='shared':steps += [explore,handoff,unrelated_handoff]
    steps += [enrich,next_check,review_inherit,more]
    if variant=='interference':steps += [noop]
    steps += [resume_first,third]
    if variant=='interference':steps += [resolve]
    steps += [noop]
    if variant=='shared':steps += [handoff]
    steps += [stop]
    e,repo=engine_for(tmp_path,steps)
    e.config.directed_question=None
    (repo/'target.py').write_text('records=[]\ndef step(value, limit):\n    result=value + 1 if value < limit else 0\n    records.append(result)\n    return result\ndef count():\n    return len(records)\ndef clear_records():\n    records.clear()\n')
    (repo/'README.md').write_text('A legal isolated call returns within capacity and appends one record before clearing.\n')
    if variant=='shared':
        e.agent.mock=False;e.config.execution_isolation='bwrap'
        p=repo/'target.py';p.write_text(p.read_text().replace('value < limit','value <= limit'))
    if variant=='shared':
        original=e.agent.investigate
        def preflight(runner,prompt,directory,snapshot_id,timeout,session_id=None):
            from consensus_assurance.workflow.audit import validate_submission
            check,session,reply=original(runner,prompt,directory,snapshot_id,timeout,session_id)
            if reply is None:return check,session,reply
            before=e.state.model_dump(mode='json')
            result=validate_submission(e.state,e.root,reply['submission'],e.implementation)
            assert result['valid'],result['diagnostics']
            assert e.state.model_dump(mode='json')==before
            return check,session,reply
        e.agent.investigate=preflight
    def interrupt(key):
        if e.state.usage.get('agent_calls')==6 and key.startswith('submission-'):
            raise KeyboardInterrupt('Second handoff prepared before adoption')
    if variant=='shared':
        e.graph_commit_hook=interrupt
        with pytest.raises(KeyboardInterrupt):e.start(repo)
        assert e.state.audit_spec_version==1
        e.graph_commit_hook=lambda key:None
        from consensus_assurance.reporting.chinese import render_report
        before=e.state.model_dump(mode='json')
        text=render_report(e.state,e.root).read_text()
        assert 'The boundary checker correspondence is pending' in text and '地图 v1' in text
        assert '对应性意见：no_issue_found' in text and '**已确认违反**' in text
        assert e.state.model_dump(mode='json')==before
        state=e.resume()
    else:state=e.start(repo)
    assert state.usage['agent_calls']==len(steps)
    assert not diagnostics(e),diagnostics(e)
    assert state.audit_spec_version==3 and len(state.units)==2
    assert state.claims[0].model_dump(mode='json')==snapshots['claim']
    assert state.direct_checks[0].model_dump(mode='json')==snapshots['artifact']
    assert state.semantic_reviews[0].model_dump(mode='json')==snapshots['review']
    assert next(c for c in state.checks if c.id==snapshots['check']['id']).model_dump(mode='json')==snapshots['check']
    assert state.units[0].version==snapshots['unit']['version']==1 and state.units[0].status=='checked'
    assert not state.revisions and state.usage.get('revisions',0)==0 and state.usage['experiments']==(3 if variant=='shared' else 2)
    assert state.usage['semantic_reviews']==(3 if variant=='interference' else 2)
    assert state.units[1].audit_question.audit_spec_version==2 and state.units[1].audit_question.fact_ids==['record']
    current=view(state)
    compact=json.loads((e.root/'research.json').read_text())
    assert len(compact['understanding_changes'])==len(current['understanding_changes'])==3
    assert compact['understanding_changes'][-1]['version']==state.audit_spec_version
    assert [h['operation_id'] for h in compact['handoffs']]==[h['operation_id'] for h in current['handoffs']]
    assert next(r for r in current['frontier']['relationships'] if r['fact_id']=='record')['consumers']
    assert current['conclusions'][0]['disposition']==('confirmed_in_scope' if variant=='shared' else 'bounded_no_violation')
    assert len(state.question_candidates)==3 and state.question_candidates[-1].status=='active'
    if variant=='interference':
        assert len(state.review_issues)==1 and state.review_issues[0].target_id==state.question_candidates[1].id
        assert state.review_issues[0].resolved_by and current['conclusions'][1]['disposition']=='bounded_no_violation'
        assert state.monitor_results[1]['bounded_complete'] and state.monitor_results[1]['reviewed_complete']
    else:
        assert state.units[1].status=='checked' and not state.review_issues
    from consensus_assurance.workflow.audit_spec import validate_units
    validate_units(state)
    assert 'External ordering between record consumption and clearing is not supplied' in current['core_overview']['open_details']
    assert not current['candidates'][0]['resume_conditions'] and current['candidates'][0]['results']
    if variant=='shared':
        handoffs=[s for s in state.selections if s['action']=='research' and s.get('feedback') and not s['map_updated']]
        assert len(handoffs)==3 and sum(s['operation_id']==snapshots['handoff_id'] for s in state.selections)==1
        assert (e.root/'audit-spec/v1.json').read_bytes()==snapshots['map1']
        spec=json.loads(Path(state.audit_spec_path).read_text())
        assert spec['behaviors'][0]['unknowns']==['Clearing schedules remain independent']
        assert 'already returned value' in spec['behaviors'][0]['important_branches'][0]
        assert 'The boundary checker correspondence is pending' not in json.dumps(spec)
        assert state.findings[0].description.startswith('Confirmed violation of:')
    # Recovery replays neither a second map event nor an execution.
    counts=(len(state.selections),[c.id for c in state.checks if c.action=='direct_check'],dict(state.usage))
    state=e.resume()
    assert (len(state.selections),[c.id for c in state.checks if c.action=='direct_check'],dict(state.usage))==counts


@pytest.mark.parametrize('disposition',['explained','closed'])
def test_new_knowledge_challenges_and_reviews_a_retained_source_explanation(tmp_path,disposition):
    def explain(state):
        sub,files=question_step(state)
        sub.update(action='explained',candidate_id=state['question_candidates'][0]['id'])
        sub.pop('map_path');files={}
        sub['question'].update(disposition='explained_by_existing_mechanism',counterevidence=['The capacity branch resets the return'])
        return sub,files
    def close(state):
        return dict(action='stop',scope='candidate',reason='bounded_completed',ref_ids=[state['question_candidates'][0]['id']],
            rationale='Close only the sourced local question'),{}
    def challenge(state):
        assert view(e.state)['units'][0]['source_explanation']
        from consensus_assurance.core.types import PendingAction
        from consensus_assurance.workflow.research import pending_work
        for change in ('claim_version','multiple_obligations','directed','in_flight','legacy'):
            copy=e.state.model_copy(deep=True)
            if change=='claim_version':copy.claims[0].version+=1
            if change=='multiple_obligations':copy.units[0].obligation_ids.append('unanswered')
            if change=='directed':copy.config['directed_question']='Execute the selected check'
            if change=='in_flight':copy.pending_action=PendingAction(kind='direct_check',unit_id=copy.units[0].id,status='running')
            if change=='legacy':
                next(s for s in copy.selections if s['action']=='explained')['accepted_versions'].pop('units')
            assert any(w['id']==copy.units[0].id for w in pending_work(copy)),change
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['facts'][0]['validity_context']='Only after a legal call with a positive limit'
        return dict(action='research',map_path='map.json',rationale='Make the previously implicit legal-input boundary explicit',
            map_changes={'result':dict(impact='meaning',source_ids=['code','doc'],rationale='Recover the documented input qualification',
                challenges={state['question_candidates'][0]['id']:'Check whether the old explanation assumed arbitrary input despite the documented precondition'})}),{'map.json':json.dumps(spec)}
    def disguised(state):
        sub,files=challenge(state);sub['map_changes']['result']['impact']='clarification'
        return sub,files
    def resolve(state):
        c=state['question_candidates'][0];issue=state['review_issues'][0]
        assert c['status']==disposition and not issue['resolved_by']
        assert not view(e.state)['units'][0]['source_explanation']
        assert {w['kind'] for w in view(e.state)['pending_work']}=={'unit','review_issue'}
        answer='The recorded question is explicitly one legal invocation; the documented positive-limit qualification does not change that source explanation'
        return dict(action='review',artifact_id=c['id'],review_items=[dict(target_id=c['id'],aspect='applicability',status='no_issue_found',
            source_ids=['code','doc'],rationale=answer)],resolutions=[dict(issue_id=issue['id'],source_ids=['code','doc'],rationale=answer,residual_issue_ids=[],scope_limitations=[])],rationale='Answer the specific knowledge challenge'),{}
    def invalid_review(state):
        sub,files=resolve(state);sub['review_items'][0]['source_ids']=['missing']
        return sub,files
    def preserve_without_resolving(state):
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['facts'][0]['unknowns']=['External consumer contract remains unread']
        return dict(action='research',map_path='map.json',rationale='Separate an independent consumer boundary from the pending qualification review',
            map_changes={'result':dict(impact='clarification',source_ids=['code','doc'],
                rationale='The additional unknown is about a later consumer',preserves='The consumer is outside the saved local question; its qualification challenge still requires review')}),{'map.json':json.dumps(spec)}
    steps=[open_first,explain]+([close] if disposition=='closed' else [])+[disguised,challenge,preserve_without_resolving,invalid_review,resolve,stop]
    e,repo=engine_for(tmp_path,steps);e.config.directed_question=None
    state=e.start(repo)
    assert len(diagnostics(e))==2 and 'review_unknown_source' in str(diagnostics(e))
    assert 'not descriptive clarification' in str(diagnostics(e))
    change=next(s for s in state.selections if s.get('map_updated') and s['accepted_versions']['audit_spec']==2)
    delta=change['map_delta']['result']
    assert delta['before']['validity_context']!=delta['after']['validity_context']
    assert state.review_issues[0].review_id==change['operation_id']
    assert state.audit_spec_version==3 and state.question_candidates[0].status==disposition
    assert state.review_issues[0].resolved_by and not state.direct_checks
    assert not view(state)['candidates'][0]['open_issue_ids']
    assert view(state)['units'][0]['source_explanation'] and not view(state)['pending_work']
    assert 'current_applicability' not in view(state)['candidates'][0]


def test_rejected_knowledge_update_cannot_leave_a_map_or_challenge(tmp_path):
    def invalid(state):
        import shutil
        from consensus_assurance.workflow.audit import validate_submission
        for fault in ('dangling','unsourced','activity_loss','base_conflict','identity_reuse','unknown_removal'):
            spec=json.loads(Path(state['audit_spec_path']).read_text())
            changes={'call':dict(impact='dependency',source_ids=['code'],rationale='A proposed newly read boundary',
                challenges={state['question_candidates'][0]['id']:'Proposed concurrent access needs investigation'})}
            if fault=='dangling':spec['behaviors'][0]['produces_fact_ids'].append('absent')
            elif fault=='unsourced':spec['behaviors'][0]['source_ids']=[]
            elif fault=='activity_loss':spec['activities'][0]['realization_summary']='Unrelated new topic overwrites the existing summary'
            elif fault=='base_conflict':spec['version']=2
            elif fault=='unknown_removal':spec['facts'][0]['unknowns']=[];changes={}
            else:
                spec['behaviors'][0]['id']='result';spec['behaviors'][0]['produces_fact_ids']=['call']
                spec['facts'][0]['id']='call';spec['facts'][0].pop('established_by')
                spec['activities'][0].pop('behavior_ids')
                changes['result']=changes['call']
            sub=dict(action='research',map_path='map.json',map_changes=changes,rationale='Submit a complete proposed update')
            root=tmp_path/fault;shutil.copytree(e.root,root)
            (root/'draft/map.json').write_text(json.dumps(spec));(root/'draft/submission.json').write_text(json.dumps(sub))
            assert not validate_submission(e.state.model_copy(deep=True),root,'submission.json',e.implementation)['valid'],fault
        return sub,{'map.json':json.dumps(spec)}

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


@pytest.mark.parametrize('violated,boundary',[(False,'calls'),(True,'deadline')])
def test_review_pause_and_reselection_continue_to_controller_boundary(tmp_path,monkeypatch,violated,boundary):
    from types import SimpleNamespace
    from consensus_assurance.workflow import budget
    from consensus_assurance.workflow.audit import validate_submission
    clock=[0.0]
    monkeypatch.setattr(budget,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    retained={}
    def early_stop(state):
        retained['artifact']=state['direct_checks'][0]
        retained['check']=next(c for c in state['checks'] if c['action']=='direct_check')
        retained['assessment']=state['monitor_results'][0]
        raw=dict(action='stop',scope='run',reason='insufficient_basis',ref_ids=['code'],
            rationale='The next complete check lacks a caller contract')
        before=e.state.model_dump(mode='json')
        for reason in ('bounded_completed','insufficient_basis','no_actionable_direction'):
            (e.root/'draft'/'stop.json').write_text(json.dumps(dict(raw,reason=reason)))
            result=validate_submission(e.state,e.root,'stop.json',e.implementation)
            assert not result['valid'] and result['diagnostics'][0]['code']=='stop_decision'
            assert result['diagnostics'][0]['details']['reconsider']=='research_decision'
        assert e.state.model_dump(mode='json')==before
        return raw,{}
    def learning(state):
        assert len(diagnostics(e))==1 and not state['run_stop']
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        spec['surfaces'].append(dict(entry_point='count',disposition='deferred',source_ids=['code'],
            reason='count reads the recorded list; the callers ordering append, count and clear remain unexamined'))
        return dict(action='research',map_path='map.json',feedback=dict(feedback(state),
            answered='count reads the process-local list length; clear_records empties the same list',
            remaining=['Read the callers ordering record creation and consumption'],understanding='updated'),
            rationale='Save the actual consumer and reset paths for another discriminator'),{'map.json':json.dumps(spec)}
    steps=[recording_first,check_step(),review_step(),next_question,local_stop('insufficient_basis'),early_stop,learning]
    e,repo=engine_for(tmp_path,steps)
    e.config.directed_question=None
    e.config.budget.total_seconds=4800
    if boundary=='deadline':e.config.budget.agent_calls=20
    source='records=[]\ndef step(value, limit):\n    result=value + 1 if value < limit else 0\n    records.append(result)\n    return result\ndef count():\n    return len(records)\ndef clear_records():\n    records.clear()\n'
    (repo/'target.py').write_text(source.replace('value + 1 if value < limit else 0','value + 1') if violated else source)
    if violated:
        e.agent.mock=False
        e.config.execution_isolation='bwrap'
    checkpoint=e.checkpoint
    def advance_clock(event):
        if boundary=='deadline' and event=='audit_execution_completed' and e.state.current_submission['action']=='research':
            clock[0]=e.config.budget.total_seconds
        checkpoint(event)
    e.checkpoint=advance_clock
    state=e.start(repo)
    assert state.agent_session_id=='fixture-session' and state.usage['agent_calls']==len(steps)
    assert state.direct_checks[0].model_dump(mode='json')==retained['artifact']
    assert next(c for c in state.checks if c.action=='direct_check').model_dump(mode='json')==retained['check']
    assert state.monitor_results[0]==retained['assessment']
    assert state.monitor_results[0]['outcome']==('violated' if violated else 'holds')
    assert state.monitor_results[0]['confirmed']==violated
    assert state.units[0].status=='checked' and state.question_candidates[1].status=='paused'
    assert state.question_candidates[1].resume_conditions and state.audit_spec_version==2
    assert state.run_stop['origin']=='controller' and state.run_stop['reason']=='resource_limit'
    assert state.usage['experiments']==1 and state.usage['semantic_reviews']==1
    assert (state.elapsed_seconds>=4800)==(boundary=='deadline')


def test_second_entry_and_consumer_reuse_fact_without_inheriting_a_result(tmp_path, full_refresh_equivalence):
    retained={}
    def initial(state):
        sub,files=recording_first(state)
        sub['sources'][0]['end_line']=7
        sub['bindings'][0].update(start_line=3,end_line=7)
        spec=json.loads(files['map.json'])
        spec['facts'][0].update(meaning='An invocation appended its returned value to the process records',
            representation=['records entry','return'],identity={'instance':'process','operation':'append occurrence'},
            validity_context='The append and return of that invocation',
            unknowns=['Ordering of other callers and record consumption is not known'])
        files['map.json']=json.dumps(spec)
        return sub,files
    def next_candidate(state):
        retained.update(unit=state['units'][0],artifact=state['direct_checks'][0],assessment=state['monitor_results'][0])
        spec=json.loads(Path(state['audit_spec_path']).read_text())
        producer=spec['behaviors'][0]
        producer.update(execution_owner='step / seed callers',trigger='step or seed invocation',
            source_ids=['code','alternate'],
            important_branches=['step appends and publishes a notification', 'seed appends without directly notifying'],
            external_effects=['Only step adds its return to notifications'],existing_protections=['step wraps at capacity; seed clamps to capacity; each appends its actual return'])
        spec['behaviors'].append(dict(id='consume',primary_activity='A1',execution_owner='consume caller',
            protocol_context='one process',trigger='consume invocation',consumes_fact_ids=['result'],source_ids=['consumer']))
        q=products()[0]['question']
        retained['branches']=producer['important_branches']
        retained['effects']=producer['external_effects']
        q.update(audit_spec_version=None,question='Does either admitted append entry wake a consumer?',
            behavior_ids=['consume'],fact_ids=['result'],source_ids=['code','alternate','consumer'],
            disposition='needs_specific_evidence',preferred_check='source_review',obligation_relation_kind='consumption',
            unknowns=['Whether notifications are required after either entry', 'Whether another scheduler invokes the consumer'],
            trigger_rationale='Read caller ownership and ordering; no established consumer obligation yet')
        preserve='The existing requirement ends at step return; adding another entry and its later consumer changes neither those fixed inputs nor the return comparison'
        return dict(action='continue',question=q,map_path='map.json',
            sources=[dict(id='alternate',file='target.py',start_line=8,end_line=11,kind='code_observation'),
                dict(id='consumer',file='target.py',start_line=12,end_line=13,kind='code_observation')],
            map_changes={id:dict(impact='dependency',source_ids=['code','alternate','consumer'],rationale=why,preserves=preserve)
                for id,why in [('call','The existing append-and-return abstraction covers the second actual entry'),
                    ('consume','The actual consumer reads the latest appended record; caller ordering remains unknown')]},
            feedback=dict(feedback(state),answered='Both entries append; only step notifies. The consumer reads the last record; its scheduling contract remains unknown',
                remaining=q['unknowns'],understanding='updated'),rationale='Investigate the distinct consumer contract from shared implementation knowledge'),{'map.json':json.dumps(spec)}
    e,repo=engine_for(tmp_path,[initial,check_step(),review_step(),next_candidate])
    e.config.directed_question=None
    (repo/'target.py').write_text('records=[]\nnotifications=[]\ndef step(value, limit):\n    result=value + 1 if value < limit else 0\n    records.append(result)\n    notifications.append(result)\n    return result\ndef seed(value, limit):\n    result=max(0, min(value, limit))\n    records.append(result)\n    return result\ndef consume():\n    return records[-1] if records else None\ndef unread(value):\n    records.append(value)\n')
    state=e.start(repo)
    assert not diagnostics(e),diagnostics(e)
    assert state.audit_spec_version==2 and len(state.question_candidates)==2
    index=json.loads((e.root/'research.json').read_text())
    spec=json.loads(Path(index['audit_spec_path']).read_text())
    producer=next(b for b in spec['behaviors'] if b['id']=='call')
    assert producer['important_branches']==retained['branches']
    assert producer['external_effects']==retained['effects']
    assert set(producer['source_ids'])=={'code','alternate'}
    fact=next(f for f in spec['facts'] if f['id']=='result')
    assert fact['established_by']==['call'] and fact['consumed_by']==['consume']
    assert len(spec['facts'])==2 and not any(b['id']=='unread' for b in spec['behaviors'])
    assert all(m.end_line<=13 for m in state.materials if m.file=='target.py')
    assert state.units[0].model_dump(mode='json')==retained['unit']
    assert state.direct_checks[0].model_dump(mode='json')==retained['artifact']
    assert state.monitor_results[0]==retained['assessment']
    assert not state.revisions and not state.review_issues
    current=view(state)
    assert len(current['conclusions'])==1 and current['conclusions'][0]['disposition']=='bounded_no_violation'
    new=state.question_candidates[-1]
    assert new.question.audit_spec_version==2 and new.question.unknowns and not new.obligation_id
    assert current['candidates'][-1]['results']==[] and len(state.claims)==1
    assert state.units[0].audit_question.audit_spec_version==1
    assert state.usage['experiments']==1 and state.usage['semantic_reviews']==1


@pytest.mark.parametrize('variant,outcome', [('overlap','violated'),('guarded','holds'),('ordered','unknown')])
def test_explanation_then_completion_discriminator_with_real_controls(tmp_path, variant, outcome):
    from audit_support import completion_target
    target=completion_target(variant)
    lines=target['target.py'].splitlines()
    binding_start=lines.index('def allowed(ticket):')+1
    def question():
        q=products()[0]['question']
        q.update(question='Can a caller report authorize consumption before actual work completion?',
            behavior_ids=['consume'],obligation_relation_kind='consumption',
            contexts=['One serialized current-generation ticket'],event_paths=['begin -> report -> allowed -> finish'],
            importance='Consumption must not treat caller notification as completed work',
            trigger_rationale='Distinguish reported admission from completed work under the documented ordering',
            unknowns=['Whether the report-before-finish schedule is permitted'])
        return q
    def explained(state):
        sub,_=first(state)
        sub.update(action='explained',obligation=None,bindings=[],question=question())
        sub['sources'][0]['end_line']=len(lines)
        sub['question'].update(question='Can a retired ticket supply current admission after advance?',
            disposition='explained_by_existing_mechanism',unknowns=[],
            counterevidence=['advance clears admission and both completion sets; public entries reject retired tickets'])
        spec=partial_map()
        spec['target_profile']['system_boundary']='One completion-admission component'
        spec['activities'][0].update(purpose='Authorize consumption from qualified current work',
            realization_summary='Current admission, reporting and completion are distinct states')
        spec['behaviors'][0].update(execution_owner='begin caller',trigger='begin',existing_protections=['Unique live ticket'])
        spec['behaviors'].append(dict(id='consume',primary_activity='A1',execution_owner='serialized caller',
            protocol_context='one generation',trigger='report, finish or allowed',consumes_fact_ids=['result'],
            important_branches=['report records notification; finish also establishes completion',
                'advance retires all tickets before the next generation'],source_ids=['code']))
        spec['facts'][0].update(meaning='The current generation admitted this unique ticket',representation=['pending'],
            identity={'ticket':'generation and request name'},validity_context='Until advance retires the ticket',
            unknowns=['Completion qualification of downstream consumption'])
        return sub,{'map.json':json.dumps(spec)}
    def investigate(state):
        assert not state['units'] and not state['checks'][-1]['direct_check_id'] and not state['evidence']
        assert state['question_candidates'][0]['status']=='explained'
        return dict(action='continue',question=question(),rationale='Investigate the distinct completion premise',
            feedback=dict(feedback(state),answered='Retired admission is explained; report and completion remain distinct current-ticket events')),{}
    def check(state):
        candidate=state['question_candidates'][1]
        sub,plan,_=products()
        sub.update(candidate_id=candidate['id'],question=dict(candidate['question']),sources=[])
        sub['question'].update(disposition='ready_for_check',unknowns=[])
        sub['feedback']=dict(feedback(state),answered='The captured contract '+
            ('permits reporting before finish; compare its actual authorization effect' if variant!='ordered' else
                'forbids early reporting; retain this deliberately inapplicable execution as a negative control, never a defect witness'))
        sub['obligation'].update(description='For compliant caller order, allowed implies completed work for this ticket',
            scope={'description':'One current ticket; report before finish where permitted','excluded':['Wider system or client consequences']})
        sub['obligation']['grounding'].update(derivation='The captured caller contract requires completed work before authorization',
            applicability='Compliant serialized calls; the ordered control forbids report-before-finish')
        sub['bindings'][0].update(symbol='allowed',start_line=binding_start,end_line=len(lines))
        plan['harness']['legality'].update(derivation='Public begin/report/allowed/finish with independent caller-order observation',
            applicability='Early report is admitted only where the captured contract permits it')
        plan['description']='Observe reporting before actual completion under explicit caller-order applicability'
        plan['harness']['description']='Public ticket calls with an independent completion ledger'
        plan['observable_properties'][0].update(checker_id='Completion',assertion={'field':'state.safe','value':True},
            description='Authorization requires actual completion')
        plan['monitors'][0].update(checker_id='Completion')
        plan['monitors'][0]['grounding'].update(derivation='Compare actual authorization to the independently controlled finish-call history',
            applicability='Same admitted current ticket')
        harness='''import json
from target import begin, report, allowed, finish
from pathlib import Path
def emit(event, **state):
    print('CA_EVENT '+json.dumps(dict(event=event,operation='one',state=state)))
ticket=begin('request')
finished=False
legal='report may precede finish.' in Path('README.md').read_text()
emit('admitted',legal=legal,ticket=ticket)
reported=report(ticket)
permitted=allowed(ticket)
emit('returned',safe=not permitted or finished,permitted=permitted,finished=finished,reported=reported,ticket=ticket)
finished=finish(ticket)
emit('control',finished=finished,permitted=allowed(ticket),ticket=ticket)
'''
        return dict(action='check',candidate=sub,plan_path='plan.json',harness_path='check.py',
            rationale='Retain the report-before-completion discriminator and independently record its applicability'),{
                'plan.json':json.dumps(plan),'check.py':harness}
    def review(state):
        sub,files=review_step()(state)
        sub['review_items'][0]['rationale']='Actual public-call history distinguishes reporting from completion; the ordered-contract negative control is inapplicable and cannot confirm a defect'
        return sub,files
    e,repo=engine_for(tmp_path,[explained,investigate,check,review])
    e.config.directed_question='Investigate the completion and generation responsibilities of this component'
    for name,content in target.items():(repo/name).write_text(content)
    e.agent.mock=False;e.config.execution_isolation='bwrap'
    state=e.start(repo)
    assert not diagnostics(e),diagnostics(e)
    assert all((repo/name).read_text()==content and (e.root/'source'/name).read_text()==content for name,content in target.items())
    first_q,second_q=state.question_candidates
    assert first_q.status=='explained' and not first_q.obligation_id and second_q.obligation_id
    assert first_q.question.fact_ids==second_q.question.fact_ids
    assert len(state.units)==len(state.direct_checks)==1 and state.usage['experiments']==state.usage['semantic_reviews']==1
    result=state.monitor_results[0]
    assert result['outcome']==outcome and result['confirmed']==(variant=='overlap')
    assert state.units[0].status==('checked' if variant!='ordered' else 'pending')
    if variant=='ordered':assert state.units[0].remaining_obligation_ids and not state.findings
    execution=next(c for c in state.checks if c.action=='direct_check')
    assert execution.snapshot_id==state.snapshot.id and execution.exit_code==0
    events=[json.loads(line.removeprefix('CA_EVENT ')) for line in Path(execution.stdout).read_text().splitlines() if line.startswith('CA_EVENT ')]
    assert events[0]['state']['legal']==(variant!='ordered')
    assert events[1]['state']['permitted']==(variant!='guarded') and not events[1]['state']['finished']
    assert events[-1]['state']['finished'] and events[-1]['state']['permitted']
    assert 'Wider system or client consequences' in state.claims[0].scope.excluded
