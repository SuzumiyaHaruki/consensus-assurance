"""Accepted research relationships through the native loop, with actual local Python tools."""
import json
from pathlib import Path
import pytest
from native_support import first, partial_map, products, engine_for, check_step, review_step, stop, feedback, defer


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
        sub['candidate']['question']['audit_spec_version']=2
        return sub,files
    def broken(state):
        sub,files=combined(state,True);sub['candidate']['question']['audit_spec_version']=2
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
    from consensus_assurance.workflow.research import view
    assert view(state)['frontier']['uninvestigated_focus']==['A2']


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


def test_continuation_accepts_same_text_new_source_but_not_rewording(tmp_path):
    def reword(state):
        sub,files=question_step(state);sub['candidate_id']=state['question_candidates'][0]['id']
        sub['question']['question']='Could this bounded boundary call exceed capacity?'
        return sub,files
    def progress(state):
        sub,files=question_step(state);sub['candidate_id']=state['question_candidates'][0]['id']
        sub['sources'].append(dict(id='consumer',file='consumer.py',start_line=1,end_line=2,kind='code_observation'))
        sub['question']['source_ids'].append('consumer')
        return sub,files
    e,repo=engine_for(tmp_path,[question_step,reword,progress,stop])
    (repo/'consumer.py').write_text('def consume(value):\n    return value\n')
    state=e.start(repo)
    assert len(state.question_candidates)==1 and len(state.question_candidates[0].history)==1
    assert state.question_candidates[0].question.question==products()[0]['question']['question']
    assert len(diagnostics(e))==1 and 'wording' in str(diagnostics(e))


def test_pause_and_result_feedback_required_before_switch_or_stop(tmp_path):
    def pause(state):
        return dict(action='pause',candidate_id=state['question_candidates'][0]['id'],question=state['question_candidates'][0]['question'],
            rationale='Need unexamined consumer code',resume_conditions=['Read actual consumer']),{}
    def independent(state):
        sub,files=first(state);sub['feedback']=feedback(state)
        return sub,files
    def omit_feedback(state):
        sub,files=first(state)
        return sub,files
    def bad_stop(state):
        return dict(action='stop',scope='run',reason='insufficient_basis',ref_ids=['code'],rationale='Try leaving pending review'),{}
    e,repo=engine_for(tmp_path,[question_step,pause,omit_feedback,independent,check_step(),bad_stop,review_step(),stop])
    state=e.start(repo)
    assert state.question_candidates[0].status=='paused'
    assert state.units[0].status=='checked' and len(diagnostics(e))==2
    from consensus_assurance.workflow.research import view
    assert not view(state)['feedback_due']
    assert view(state)['paused_candidates']


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
            draft.audit_question.audit_spec_version=2
            patch=GraphPatch(units=[draft],expected_versions={unit.id:unit.version},rationale=sub['rationale'])
            writes=write_set(saved,patch)
            fb=dict(kind='F2',rationale=sub['rationale'],evidence_ids=['code','doc'],target_ids=[unit.id],relation_ids=[],
                new_basis='The acquired contract applies only to admitted inputs; reconnect the scoped question explicitly',
                old_judgment='Only delivery is described',new_judgment='The local contract-bound return is described',
                graph=None,bundle=None,patch=patch.model_dump(mode='json'),grounding=products()[0]['obligation']['grounding'],
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
        draft.audit_question.audit_spec_version=2
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
        from consensus_assurance.workflow.research import feedback_due
        from consensus_assurance.core.types import Analysis
        assert not feedback_due(Analysis.model_validate(state))
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
        questions={c['id']:{**c['question'],'audit_spec_version':2} for c in state['question_candidates']}
        return dict(action='research',map_path='map.json',reconnect_questions=questions,
            map_changes={'result':dict(impact='meaning',source_ids=['code'],rationale='Clarify the bounded lifetime before deriving either obligation')},
            rationale='Reconnect both sourced hypotheses to the revised Fact without changing their status'),{'map.json':json.dumps(spec)}
    e,repo=engine_for(tmp_path,[question_step,pause,other,reconnect,stop])
    state=e.start(repo)
    assert not diagnostics(e),diagnostics(e)
    assert state.audit_spec_version==2 and [c.status for c in state.question_candidates]==['paused','active']
    assert all(c.question.audit_spec_version==2 and c.history for c in state.question_candidates)
