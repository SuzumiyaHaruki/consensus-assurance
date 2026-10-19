"""Method continuity through the normal loop; supplied fixture expectations are not discovery evidence."""
import json
import pytest
from support.audit import engine_for, first, combined, experiment, opinion, stop
from consensus_assurance.workflow.experiments import assessment
from consensus_assurance.workflow.knowledge import open_gaps
from consensus_assurance.workflow.research import operation_summary


@pytest.mark.real
def test_test_selection_is_fixed_across_repeat_and_changed_as_successor(tmp_path, go_module):
    import shutil
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.adapters.runners.experiment import extract_events
    if not shutil.which('go'):
        pytest.skip('Go unavailable')
    harness = '''package service
import ("fmt"; "testing")
func TestAssuranceA(t *testing.T) { fmt.Println(`CA_EVENT {"event":"A"}`) }
func TestAssuranceB(t *testing.T) { fmt.Println(`CA_EVENT {"event":"B"}`) }
func TestAssuranceOld(t *testing.T) { t.Fatal("Unselected old case") }
'''
    def start(state):
        return {'rationale':'Select one generated test',
            'sources':[dict(id='code',file='value.go',start_line=1,end_line=4,kind='code_observation')],
            'investigations':[dict(ref='@q',question='Observe selected cases',source_ids=['code'])],
            'experiment':dict(investigation_id='@q',harness_path='check.go',source_ids=['code'],
                scope={'description':'Selected generated test'},prefix='Invoke the selected test',test_names=['TestAssuranceA'])}, {'check.go':harness}
    def repeat(state):
        return {'rationale':'Repeat the saved selection', 'repeat_experiment_id':state['experiments'][0]['id']}, {
            'check.go':'package service\n', 'unused-selection.json':'["TestAssuranceB"]'}
    def successor(state):
        sub,files=start(state)
        return {'rationale':'Select a different case from the same retained code', 'experiment':{
            **sub['experiment'], 'investigation_id':state['investigations'][0]['id'],
            'test_names':['TestAssuranceB'], 'previous_id':state['experiments'][0]['id'],
            'revision_reason':'Select case B instead of A'}},files
    engine,repo=engine_for(tmp_path,[start,repeat,successor,stop])
    shutil.copytree(go_module,repo,dirs_exist_ok=True)
    engine.implementation=GoModuleBackend()
    engine.config.execution_backend='go_module'
    state=engine.start(repo)
    assert len(state.experiments)==2 and state.usage['experiments']==3
    old,new=state.experiments
    assert old.basis.harness.test_names==['TestAssuranceA']
    assert new.previous_id==old.id and new.basis.harness.test_names==['TestAssuranceB']
    checks=[c for c in state.checks if c.action=='experiment']
    assert [[event['event'] for event in extract_events(c)] for c in checks]==[['A'],['A'],['B']]
    assert [c.experiment_id for c in checks]==[old.id,old.id,new.id]
    from consensus_assurance.workflow.research import execution_feedback
    assert execution_feedback(state,engine.root,new,checks[-1])['test_selection']['requested']==['TestAssuranceB']


@pytest.mark.parametrize('gap', [False, True])
def test_combined_submission_execution_interpretation_and_noop(tmp_path, gap):
    retained = {}
    def interpret(state):
        question, = operation_summary(e.state, e.root)['questions']
        retained['execution'] = question['execution']['id']
        assert question['execution']['comparisons'][0]['result']['valid_witness_indices'] == [1]
        assert not state['interpretations']
        sub, files = opinion(state)
        if gap:
            sub['gaps'] = [dict(investigation_id=state['investigations'][0]['id'],
                experiment_id=state['experiments'][0]['id'], question='Does the producer establish the sampled input?')]
        return sub, files
    def duplicate(state):
        summary = operation_summary(e.state, e.root)
        assert summary['questions'][0]['latest_interpretation']['id'] == state['interpretations'][0]['id']
        assert summary['interpretation_changes'][0]['executions'][0]['id'] == retained['execution']
        return opinion(state)
    def finish(state):
        summary = operation_summary(e.state, e.root)
        assert summary['no_change'] and not summary['questions'] and 'interpretation_changes' not in summary
        assert bool(summary['necessary_gaps']) == gap
        return stop(state)
    e, repo = engine_for(tmp_path, [combined, interpret, duplicate, finish])
    state = e.start(repo)
    assert len(state.investigations) == len(state.experiments) == len(state.interpretations) == 1
    assert state.usage == {'agent_calls': 4, 'experiments': 1} and state.agent_session_id == 'fixture-session'
    index = json.loads((e.root/'research.json').read_text())['investigations'][0]
    assert index['latest_execution']['id'] == retained['execution']
    assert index['latest_interpretation']['executions'] == {retained['execution']: [1]}
    check = next(c for c in state.checks if c.id == retained['execution'])
    result = assessment(state, e.root, state.experiments[0], check)
    assert result['outcome'] == 'violated' and 'Scripted or nonoriginal execution' in str(result['blockers'])


def test_interpretation_correction_keeps_its_own_receipts_after_another_question_executes(tmp_path):
    def another(state):
        request, files = experiment('@other')
        return {'rationale': 'Observe an independent caller',
            'investigations': [dict(ref='@other', question='What does another caller observe?', source_ids=['code'])],
            'experiment': request}, files

    def correct(state):
        old = state['interpretations'][0]
        return opinion(state, investigation_id=old['investigation_id'], experiment_id=old['experiment_id'],
            executions=old['executions'], conclusion='explained', defect_claim='refuted',
            counterevidence=['The cited contract permits the observed return'],
            rationale='Source research refutes the earlier defect claim without changing the observation')

    def finish(state):
        change, = operation_summary(e.state, e.root)['interpretation_changes']
        old, current = state['interpretations']
        assert change['previous']['id'] == old['id'] and change['current']['id'] == current['id']
        receipt, = change['executions']
        assert receipt['experiment_id'] == state['experiments'][0]['id']
        assert receipt['current_event_indices'] == receipt['previous_event_indices'] == [1]
        assert old['defect_claim'] == 'asserted' and current['defect_claim'] == 'refuted'
        assert old['executions'] == current['executions']
        return stop(state)

    e, repo = engine_for(tmp_path, [combined, lambda state: opinion(state, defect_claim='asserted'), another, correct, finish])
    state = e.start(repo)
    assert state.usage['experiments'] == 2 and len(state.interpretations) == 2


def test_preflight_is_readonly_and_predicts_execution(tmp_path, monkeypatch):
    from consensus_assurance.workflow.audit import validate_submission
    from consensus_assurance.adapters.runners.process import ProcessRunner

    def validate(sub, files, expected):
        for name, content in {**files, 'preflight.json': json.dumps(sub)}.items():
            (e.root / 'draft' / name).write_text(content)
        before = e.state.model_dump(mode='json')
        saved = {p: p.read_bytes() for p in e.root.rglob('*') if p.is_file()}
        with monkeypatch.context() as patch:
            patch.setattr(ProcessRunner, 'run', lambda *a, **kw: pytest.fail('Preflight cannot execute'))
            result = validate_submission(e.state, e.root, 'preflight.json', e.implementation)
        assert result['valid']
        assert (result['no_change'], result['execution_requested']) == expected
        assert e.state.model_dump(mode='json') == before
        assert {p: p.read_bytes() for p in e.root.rglob('*') if p.is_file()} == saved

    def start(state):
        sub, files = combined(state)
        validate(sub, files, (False, True))
        return sub, files

    def inspect(state):
        request, files = experiment(state['investigations'][0]['id'])
        validate({'rationale': 'Identical effective input', 'experiment': request}, files, (True, False))
        validate(*opinion(state), (False, False))
        validate({'rationale': 'Explicitly repeat retained input',
                  'repeat_experiment_id': state['experiments'][0]['id']}, {}, (False, True))
        return stop(state)

    e, repo = engine_for(tmp_path, [start, inspect])
    state = e.start(repo)
    assert len(state.experiments) == 1 and not state.interpretations
    assert state.usage == {'agent_calls': 2, 'experiments': 1}


def test_source_only_answer_and_exact_noop_keep_cost_without_revisions(tmp_path):
    prompts = []
    def answer(state):
        q = state['investigations'][0]['id']
        return {'rationale': 'Existing sources explain this local branch',
            'investigations': [dict(id=q, disposition='explained')],
            'interpretations': [dict(investigation_id=q, source_ids=['code'], conclusion='explained',
                defect_claim=None, rationale='The boundary branch is directly visible in the cited source')]}, {}

    def finish(state):
        assert state['current_submission']['no_change']
        assert len(state['interpretations']) == 1 and state['investigations'][0]['version'] == 2
        actual = json.loads(prompts[-1].split('Current work (controller records):\n', 1)[1])
        ordinary = operation_summary(e.state, e.root)
        assert actual['next'] != ordinary['next']
        assert actual['operation_id'] == ordinary['operation_id']
        assert actual['necessary_gaps'] == ordinary['necessary_gaps']
        assert actual['reselection']['questions'] == ordinary['reselection']['questions']
        return stop(state)

    e, repo = engine_for(tmp_path, [first, answer, answer, finish])
    investigate = e.agent.investigate
    def completed_turn(runner, prompt, *args):
        prompts.append(prompt)
        check, session, result = investigate(runner, prompt, *args)
        check.pending_action_id = runner.active_action_id
        check.ended_at = '2026-01-01T00:00:01+00:00'
        check.parameters.update(agent_turn_completed=bool(result), agent_tool_events=0,
            agent_diagnostic=dict(message='', transport_failure=False, session_unavailable=False))
        return check, session, result
    e.agent.investigate = completed_turn
    state = e.start(repo)
    assert state.usage == {'agent_calls': 4} and not state.experiments
    assert len(list((e.root / 'submissions').glob('*/raw.json'))) == 3


def test_gap_answers_survive_omission_and_can_be_reopened(tmp_path):
    def start(state):
        sub, files = combined(state)
        sub['gaps'] = [dict(investigation_id='@q', question='Does the caller establish the required input?')]
        return sub, files

    def answer(state, resolved):
        gap = state['investigations'][0]['gaps'][0]['id']
        return opinion(state, answers={gap: dict(resolved=resolved,
            explanation='The sourced caller establishes the input' if resolved else 'The actual caller remains unestablished')})

    def child(state):
        q = state['investigations'][0]['id']
        return {'rationale': 'Explain a narrower child without closing its parent',
            'investigations': [dict(parent_id=q, question='What does the expression return?',
                source_ids=['code'], disposition='explained')]}, {}

    def resolve(state):
        assert open_gaps(e.state, state['investigations'][0]['id'])
        assert not state['interpretations'][-1]['answers']
        return answer(state, True)

    def reopen(state):
        assert not open_gaps(e.state, state['investigations'][0]['id'])
        assert not state['interpretations'][-1]['answers']
        return answer(state, False)

    e, repo = engine_for(tmp_path, [start, child, lambda s: answer(s, False), opinion,
                                   resolve, opinion, reopen, stop])
    state = e.start(repo)
    assert open_gaps(state, state.investigations[0].id)
    assert state.investigations[0].disposition == 'active'
    assert state.investigations[1].parent_id == state.investigations[0].id
    assert [next(iter(i.answers.values())).resolved for i in state.interpretations if i.answers] == [False, True, False]
    assert state.usage['experiments'] == 1


@pytest.mark.parametrize('fault', ['source_path', 'knowledge_entry', 'knowledge_revision', 'missing_claim', 'unknown_gap', 'question_boundaries'])
def test_source_paths_and_whole_draft_repair_are_atomic(tmp_path,fault):
    def bad(state):
        sub,files=combined(state)
        if fault=='source_path':
            sub['sources'][0]['file']='../outside.py'
        elif fault in {'missing_claim','unknown_gap'}:
            sub['interpretations']=[dict(investigation_id='@q',source_ids=['code'],conclusion='explained',
                rationale='The boundary expression returns zero')]
            if fault=='unknown_gap':
                sub['interpretations'][0].update(defect_claim=None,
                    answers={'missing':dict(explanation='A nonexistent gap cannot be answered',resolved=True)})
        elif fault=='question_boundaries':
            sub['investigations'][0]['limitations']=['Interpretation owns current evidence boundaries']
        else:
            sub['knowledge']=[dict(ref='@behavior',kind='behavior',statement='The boundary returns zero',
                conditions='Capacity input',source_ids=['code']),
                dict(kind='fact',statement='The boundary return remains bounded',conditions='Positive capacity',
                    source_ids=['code','doc'],knowledge=[dict(
                        entry_id='missing' if fault=='knowledge_entry' else '@behavior',revision=2)])]
        return sub,files
    def repaired(state):
        assert not state['investigations'] and not state['experiments'] and not state['knowledge']
        assert state['current_submission']['phase']=='rejected'
        sub,files=combined(state)
        sub['interpretations']=[dict(investigation_id='@q',source_ids=['code'],conclusion='explained',
            defect_claim=None,rationale='The boundary expression returns zero',
            limitations=['No broader contract conclusion follows'])]
        return sub,files
    e,repo=engine_for(tmp_path,[bad,repaired,stop])
    state=e.start(repo)
    assert len(state.experiments)==1 and state.usage['experiments']==1
    rejection=next((e.root/'submissions').glob('*/diagnostics.json'))
    raw=json.loads((rejection.parent/'raw.json').read_text())
    if fault=='source_path':
        assert raw['sources'][0]['file']=='../outside.py'
    elif fault.startswith('knowledge'):
        assert raw['knowledge'][1]['knowledge']
    elif fault=='missing_claim':
        assert 'defect_claim' not in raw['interpretations'][0]
    assert state.interpretations[0].defect_claim is None
    assert state.interpretations[0].limitations==['No broader contract conclusion follows']
    assert not {'counterevidence','limitations'} & state.investigations[0].model_dump().keys()
    assert (rejection.parent/'inputs/check.py').is_file()==(fault not in {'missing_claim','question_boundaries'})


def test_revision_needs_own_execution_but_interpretation_correction_does_not(tmp_path):
    def revise(state):
        assert len(state['interpretations'])==3
        if len(state['experiments'])==1:
            assert state['current_submission']['no_change']
        a=state['experiments'][-1]
        request,files=experiment(a['investigation_id'])
        request.update(previous_id=a['id'],revision_reason='Correct the expected return from the boundary contract')
        request['comparisons'][0]['assertion']={'field':'value','value':0}
        return {'rationale':'Use a successor for the changed predicate','experiment':request},files
    def corrected(state):
        return opinion(state,experiment_id=None,executions={},conclusion='unresolved',defect_claim='refuted',
            rationale='The newly inspected calling contract changes the earlier interpretation')
    def restore(state):
        return opinion(state,defect_claim='asserted')
    def duplicate(state):
        sub, files = revise(state)
        sub['experiment']['previous_id'] = state['experiments'][0]['id']
        return sub, files
    def finish(state):
        assert state['current_submission']['no_change']
        return stop(state)
    e,repo=engine_for(tmp_path,[combined,restore,corrected,restore,restore,revise,duplicate,finish])
    state=e.start(repo)
    assert len(state.experiments)==2 and state.usage['experiments']==2
    old,new=state.experiments
    assert new.previous_id==old.id and 'comparisons' in new.difference
    old_check=next(c for c in state.checks if c.experiment_id==old.id)
    new_check=next(c for c in state.checks if c.experiment_id==new.id)
    assert assessment(state,e.root,old,old_check)['outcome']=='violated'
    assert assessment(state,e.root,new,new_check)['outcome']=='holds'
    assert assessment(state,e.root,new,new_check)['interpretation_id'] is None
    assert [i.defect_claim for i in state.interpretations]==['asserted','refuted','asserted']
    assert state.interpretations[0].executions==state.interpretations[-1].executions


def test_gap_lineage_diagnostic_allows_question_level_correction_with_actual_receipts(tmp_path):
    retained={}
    def start(state):
        sub,files=combined(state)
        files['check.py'] += "for i in range(10): print('CA_EVENT '+json.dumps(dict(event='extra',operation=str(i))))\n"
        return sub,files
    def independent(state):
        old=state['experiments'][0]
        retained['basis']=(e.root/'fixed-experiments'/old['id']/'basis.json').read_bytes()
        request,files=experiment(old['investigation_id'])
        request['comparisons'][0]['assertion']={'field':'value','value':0}
        return {'rationale':'Check a separate predicate without claiming a predecessor', 'experiment':request,
            'gaps':[dict(investigation_id=old['investigation_id'],experiment_id=old['id'],
                question='Does the caller contract support the original expectation?')]},files
    def answer(state):
        return opinion(state,conclusion='explained',defect_claim='refuted',
            executions={c['id']:(list(range(1,12)) if c['experiment_id']==state['experiments'][0]['id'] else [1])
                for c in state['checks'] if c.get('experiment_id')},
            joint_history='Two independent calls to the same stateless boundary function',
            answers={state['investigations'][0]['gaps'][0]['id']:dict(resolved=True,
                explanation='The documented bound permits the observed zero; equality to the input was too strong')})
    def repair(state):
        diagnostic,=state['current_submission']['rejected']['diagnostics']
        old,new=state['experiments'];gap=state['investigations'][0]['gaps'][0]
        assert diagnostic['code']=='gap_lineage'
        assert diagnostic['details']==dict(investigation_id=old['investigation_id'],experiment_id=new['id'],
            experiment_lineage=[new['id']],gap_experiments={gap['id']:old['id']})
        assert diagnostic['paths']==['/interpretations/0/experiment_id','/interpretations/0/answers']
        assert 'retaining actual execution citations' in diagnostic['message']
        assert not state['interpretations'] and open_gaps(e.state,old['investigation_id'])
        sub,files=answer(state)
        sub['interpretations'][0]['experiment_id']=None
        return sub,files
    def finish(state):
        receipts=operation_summary(e.state,e.root)['interpretation_changes'][0]['executions']
        assert sum(len(r['cited_events']) for r in receipts)==8
        assert all(r['event_indices']==[v['event_index'] for v in r['cited_events']]+r['omitted_cited_indices'] for r in receipts)
        assert receipts[1]['cited_events']==[] and receipts[1]['omitted_cited_indices']==[1]
        return stop(state)
    e,repo=engine_for(tmp_path,[start,independent,answer,repair,finish])
    state=e.start(repo)
    assert state.usage['experiments']==2 and len(state.interpretations)==1
    assert len(state.interpretations[0].executions)==2 and not open_gaps(state,state.investigations[0].id)
    assert all(a.previous_id is None for a in state.experiments)
    assert (e.root/'fixed-experiments'/state.experiments[0].id/'basis.json').read_bytes()==retained['basis']


@pytest.mark.parametrize('directed', [False, True])
def test_only_finite_answered_task_can_complete_early(tmp_path, directed):
    def finish(state):
        sub, files = first(state)
        sub['investigations'][0]['disposition'] = 'explained'
        sub['interpretations'] = [dict(investigation_id='@q', source_ids=['code'], conclusion='explained',defect_claim=None,
                                      rationale='The visible local boundary branch returns zero')]
        sub['stop'] = dict(reason='bounded_completed', rationale='The finite local source question is answered')
        return sub, files

    engine, repo = engine_for(tmp_path, [finish, stop])
    if not directed:
        engine.config.directed_question = None
    state = engine.start(repo)
    if directed:
        assert state.run_stop['reason'] == 'bounded_completed'
        assert state.usage['agent_calls'] == 1
    else:
        assert not state.investigations and not state.interpretations
        assert list((engine.root / 'submissions').glob('*/diagnostics.json'))
        assert state.usage['agent_calls'] == 2


def test_evidence_enrichment_preserves_used_premise_and_exploratory_results(tmp_path):
    def probe(state):
        sub, files = combined(state)
        for key in ('requirement', 'responsibility', 'comparisons', 'anchors'):
            sub['experiment'].pop(key)
        if state['experiments']:
            assert state['experiments'] == before[0] and not state['investigations'][0]['gaps']
            sub.pop('investigations')
            sub.pop('sources')
            sub['experiment'].update(investigation_id=state['investigations'][0]['id'],
                previous_id=state['experiments'][0]['id'], revision_reason='Sample another legal capacity input',
                knowledge=[dict(entry_id=state['knowledge'][0]['id'], revision=1)])
            files['check.py'] = files['check.py'].replace('3', '4')
        return sub, files

    before = []

    def knowledge(state):
        before.append(state['experiments'])
        return {'rationale': 'Retain the sourced premise with its actual samples', 'knowledge': [dict(
            ref='@behavior', id=state['knowledge'][0]['id'] if state['knowledge'] else None,
            kind='behavior', statement='The function returns zero at capacity', conditions='value equals limit',
            source_ids=['code'], executions={c['id']:[1] for c in state['checks'] if c.get('experiment_id')})],
            'investigations':[dict(id=state['investigations'][0]['id'],
                knowledge=[dict(entry_id='@behavior',revision=1)])]}, {}

    def finish(state):
        summary=operation_summary(engine.state,engine.root)
        assert 'knowledge_corrections' not in summary
        change,=summary['knowledge_changes']
        assert (change['previous']['revision'],change['current']['revision'])==(1,2)
        assert change['previous']['statement']==change['current']['statement']==state['knowledge'][0]['statement']
        assert len(change['executions'])==2 and all(r['cited_events'] for r in change['executions'])
        return stop(state)
    engine, repo = engine_for(tmp_path, [probe, knowledge, probe, knowledge, finish])
    state = engine.start(repo)
    assert [a.model_dump(mode='json') for a in state.experiments] == before[-1]
    entry = state.knowledge[0]
    assert entry.revision == 2 and len(entry.history) == 1 and len(entry.executions) == 2
    history = entry.history[0]
    assert (entry.statement, entry.conditions) == (history['statement'], history['conditions'])
    assert not history['correction'] and not history['affected_uses'] and not state.investigations[0].gaps
    assert set(history['recorded_uses']) == {state.investigations[0].id, state.experiments[1].id}
    assert len(history['executions']) == 1 and history['executions'].items() <= entry.executions.items()
    assert state.investigations[0].knowledge[0].revision == state.experiments[1].basis.knowledge[0].revision == 1
    for fixed in state.experiments:
        check = next(c for c in state.checks if c.experiment_id == fixed.id)
        result = assessment(state, engine.root, fixed, check)
        assert result['events'][1]['value'] == 0
        assert result['outcome'] == 'unknown' and not result['comparisons']
    index = json.loads((engine.root/'research.json').read_text())['knowledge'][0]
    assert index['revision'] == 2 and set(index['executions']) == set(entry.executions)
    assert index['last_correction']['correction'] == '' and index['last_correction']['recorded_uses'] == history['recorded_uses']


@pytest.mark.parametrize('recorded', [False, True])
def test_knowledge_correction_diagnostic_identifies_invalid_uses_and_allows_repair(tmp_path,recorded):
    def start(state):
        sub,files=first(state)
        sub['knowledge']=[dict(ref='@premise',kind='behavior',statement='The boundary preserves its input',
            conditions='Capacity input',source_ids=['code'])]
        if recorded:sub['investigations'][0]['knowledge']=[dict(entry_id='@premise',revision=1)]
        return sub,files
    def correction(state,invalid=False):
        uses=[state['investigations'][0]['id']] if recorded else []
        return {'rationale':'Correct the sourced boundary account', 'knowledge':[dict(
            id=state['knowledge'][0]['id'],kind='behavior',statement='The boundary returns zero',
            conditions='Capacity input',source_ids=['code'],
            changed_premise='Zero does not preserve the capacity input',
            affected_uses=uses+(['unrecorded-question'] if invalid else []))]},{}
    def repair(state):
        assert state['current_submission']['phase']=='rejected'
        diagnostic=str(state['current_submission']['rejected'])
        assert "Invalid affected_uses IDs: ['unrecorded-question']" in diagnostic
        expected=[state['investigations'][0]['id']] if recorded else []
        assert f'valid recorded use IDs: {expected}' in diagnostic
        assert 'changed_premise as a semantic explanation' in diagnostic
        assert state['knowledge'][0]['revision']==1 and not state['investigations'][0]['gaps']
        return correction(state)
    e,repo=engine_for(tmp_path,[start,lambda state:correction(state,True),repair,stop])
    state=e.start(repo)
    assert state.knowledge[0].revision==2
    assert state.knowledge[0].history[0]['correction']=='Zero does not preserve the capacity input'
    assert bool(state.investigations[0].gaps)==recorded


def test_knowledge_correction_tracks_historical_dependencies_without_rewriting_evidence(tmp_path):
    def initial(state):
        sub, files = combined(state)
        sub['knowledge'] = [dict(ref='@premise', kind='behavior', statement='The boundary preserves its input',
            conditions='Capacity input', source_ids=['code']),
            dict(ref='@fact', kind='fact', statement='The boundary retains the admitted value',
                conditions='Capacity input', source_ids=['code'], knowledge=[dict(entry_id='@premise', revision=1)])]
        sub['investigations'][0]['knowledge'] = [dict(entry_id='@fact', revision=1)]
        sub['experiment']['knowledge'] = [dict(entry_id='@fact', revision=1)]
        return sub, files

    def unrelated(state):
        fact = state['knowledge'][1]
        return {'rationale': 'Source the new bound independently of the old preservation premise',
            'knowledge': [dict(id=fact['id'], kind='fact', statement='The return is within documented bounds',
                conditions='Legal capacity input', source_ids=['doc'], knowledge=[],
                changed_premise='The bounded return no longer depends on input preservation')],
            'investigations': [dict(question='Which bounds apply to another caller?', source_ids=['doc'],
                knowledge=[dict(entry_id=fact['id'], revision=2)])]}, {}

    retained = {}

    def correct(state):
        assert not any(q['gaps'] for q in state['investigations'])
        retained['interpretations'] = state['interpretations']
        retained['checks'] = {p: p.read_bytes() for p in (e.root / 'logs').rglob('*') if p.is_file()}
        retained['correction'] = dict(id=state['knowledge'][0]['id'], kind='behavior',
            statement='The boundary returns zero', conditions='Capacity input', source_ids=['code'],
            changed_premise='Zero does not preserve the capacity input',
            affected_uses=[state['investigations'][0]['id']])
        return {'rationale': 'Correct the premise used by the earlier derived revision',
                'knowledge': [retained['correction']]}, {}

    def supplement(state):
        assert len(state['investigations'][0]['gaps']) == 1
        retained['correction']['affected_uses'].append(state['experiments'][0]['id'])
        return {'rationale': 'Record the later identified experiment impact', 'knowledge': [retained['correction']]}, {}

    def finish(state):
        correction, = operation_summary(e.state, e.root)['knowledge_corrections']
        assert set(correction['recorded_uses']) == {state['investigations'][0]['id'], state['experiments'][0]['id']}
        assert set(correction['affected_uses']) == set(correction['recorded_uses'])
        assert state['interpretations'] == retained['interpretations']
        assert not state['investigations'][1]['gaps']
        assert state['knowledge'][1]['history'][0]['knowledge'][0]['revision'] == 1
        assert state['experiments'][0]['basis']['knowledge'][0]['revision'] == 1
        assert all(p.read_bytes() == data for p, data in retained['checks'].items())
        return {'rationale': 'Repeat unchanged correction', 'knowledge': [retained['correction']]}, {}

    def duplicate(state):
        assert state['current_submission']['no_change'] and state['knowledge'][0]['revision'] == 3
        assert len(state['investigations'][0]['gaps']) == 2
        return stop(state)

    e, repo = engine_for(tmp_path, [initial, opinion, unrelated, correct, supplement, finish, duplicate])
    state = e.start(repo)
    assert state.usage['experiments'] == 1 and len(state.interpretations) == 1
