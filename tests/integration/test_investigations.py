"""Method continuity through the normal loop; supplied fixture expectations are not discovery evidence."""
import json
from pathlib import Path
import pytest
from audit_support import engine_for, first, combined, experiment, opinion, stop
from consensus_assurance.core.submissions import AuditSubmission
from consensus_assurance.workflow.experiments import assessment
from consensus_assurance.workflow.knowledge import open_gaps
from consensus_assurance.workflow.research import operation_summary, excerpt


@pytest.mark.parametrize('gap',[False,True])
def test_combined_local_start_and_interpretation_feedback(tmp_path,gap):
    seen = []
    def interpret(state):
        seen.append(json.loads((e.root/'research.json').read_text()))
        sub,files=opinion(state)
        if gap:sub['gaps']=[dict(investigation_id=state['investigations'][0]['id'],
            experiment_id=state['experiments'][0]['id'],question='Does the producer establish the sampled input?')]
        return sub,files
    def duplicate(state):
        assert operation_summary(e.state,e.root)['questions'][0]['latest_interpretation']['id']==state['interpretations'][0]['id']
        return opinion(state)
    def finish(state):
        index = json.loads((e.root/'research.json').read_text())
        assert index['investigations'][0]['latest_execution'] == seen[0]['investigations'][0]['latest_execution']
        assert index['investigations'][0]['latest_interpretation']['executions']
        summary=operation_summary(e.state,e.root)
        assert summary['no_change'] and not summary['questions']
        assert bool(summary['necessary_gaps'])==gap
        if gap:assert summary['necessary_gaps'][0]['investigation_id']==state['investigations'][0]['id']
        assert summary['reselection']['questions'][0]['latest_interpretation']['id']==state['interpretations'][0]['id']
        actual=summary['latest_actual_execution']
        fixed=state['experiments'][0]
        check=next(c for c in state['checks'] if c.get('experiment_id')==fixed['id'])
        assert (actual['experiment_id'],actual['investigation_id'])==(fixed['id'],fixed['investigation_id'])
        assert json.loads((e.root/actual['basis']).read_text())['id']==fixed['id']
        assert (e.root/actual['harness']).read_text()==fixed['basis']['harness']['source']
        assert (actual['stdout'],actual['stderr'])==(check['stdout'],check['stderr'])
        assert 'CA_EVENT ' in Path(actual['stdout']).read_text() and Path(actual['stderr']).is_file()
        return stop(state)
    e, repo = engine_for(tmp_path,[combined,interpret,duplicate,finish])
    state = e.start(repo)
    assert len(state.investigations) == len(state.experiments) == len(state.interpretations) == 1
    assert state.usage == {'agent_calls':4,'experiments':1}
    assert state.agent_session_id == 'fixture-session'
    fixed = state.experiments[0]
    check = next(c for c in state.checks if c.experiment_id == fixed.id)
    result = assessment(state,e.root,fixed,check)
    assert result['outcome'] == 'violated' and 'Scripted or nonoriginal execution' in str(result['blockers'])
    assert result['comparisons'][0]['valid_witness_indices'] == [1]
    assert not any(name in type(state).model_fields for name in ('units','claims','bindings','relations','evidence','findings'))


def test_preflight_reports_effect_without_acceptance_or_execution(tmp_path,monkeypatch):
    from consensus_assurance.workflow.audit import validate_submission
    from consensus_assurance.adapters.runners.process import ProcessRunner
    def validate(sub,files,effects):
        for name,content in {**files,'preflight.json':json.dumps(sub)}.items():
            (e.root/'draft'/name).write_text(content)
        before=e.state.model_dump(mode='json')
        saved={p:p.read_bytes() for p in e.root.rglob('*') if p.is_file()}
        with monkeypatch.context() as patch:
            patch.setattr(ProcessRunner,'run',lambda *a,**kw:pytest.fail('Preflight cannot execute'))
            result=validate_submission(e.state,e.root,'preflight.json',e.implementation)
        assert result['valid']==(effects is not None)
        if effects is None:
            assert result['diagnostics'] and not {'no_change','execution_requested','effects'} & result.keys()
        else:assert (result['no_change'],result['execution_requested'])==effects
        assert e.state.model_dump(mode='json')==before
        assert {p:p.read_bytes() for p in e.root.rglob('*') if p.is_file()}==saved
        assert not any('preflight-' in json.dumps(effect) for effect in result.get('effects',[]))
        return result.get('effects',[])
    def start(state):
        sub,files=combined(state)
        sub['knowledge']=[dict(ref='@behavior',kind='behavior',statement='The target returns a bounded value.',
                               conditions='A local synchronous call',source_ids=['code'])]
        effects=validate(sub,files,(False,True))
        assert {'object':'investigations','action':'create','target':'@q'} in effects
        assert {'object':'knowledge','action':'create','target':'@behavior'} in effects
        assert {'object':'experiments','action':'create','target':'experiment'} in effects
        return sub,files
    def inspect(state):
        q=state['investigations'][0]['id']
        request,files=experiment(q)
        assert validate({'rationale':'Identical effective experiment','experiment':request},files,(True,False))==[
            {'object':'experiments','action':'unchanged'}]
        assert validate(*opinion(state),(False,False))==[
            {'object':'interpretations','action':'append','target':'interpretations[0]','investigation_id':q}]
        sub,files=opinion(state)
        sub['sources']=[dict(id='extra-code',file='target.py',start_line=1,end_line=2,kind='code_observation')]
        sub['investigations']=[dict(question=state['investigations'][0]['question'],source_ids=['code','doc','extra-code'])]
        effects=validate(sub,files,(False,False))
        assert {'object':'investigations','action':'create','target':'investigations[0]'} in effects
        assert next(x for x in effects if x['object']=='interpretations')['investigation_id']==q
        sub['investigations'][0]['id']=q
        effect=next(x for x in validate(sub,files,(False,False)) if x['object']=='investigations')
        assert effect=={'object':'investigations','action':'update','target':q,'changed_fields':['source_ids']}
        assert validate({'rationale':'Retain a necessary gap','gaps':[dict(investigation_id=q,question='Is the caller input legal?')]},{},(False,False))==[
            {'object':'investigations','action':'update','target':q,'changed_fields':['gaps']}]
        entry=state['knowledge'][0]
        change={key:entry[key] for key in ('id','kind','statement','conditions','source_ids')}
        change['statement']='The boundary path returns zero.'
        assert validate({'rationale':'Correct the source explanation','knowledge':[change]},{},(False,False))==[
            {'object':'knowledge','action':'update','target':entry['id'],'changed_fields':['statement']}]
        assert validate({'rationale':'Reproduce the fixed input','repeat_experiment_id':state['experiments'][0]['id']},{},(False,True))==[
            {'object':'experiments','action':'repeat_execution','target':state['experiments'][0]['id']}]
        validate({'rationale':'Unknown retained input','repeat_experiment_id':'absent'},{},None)
        sub,files=opinion(state)
        sub['investigations']=[dict(id=q,disposition='explained')]
        return sub,files
    def finish(state):
        effects=validate(*opinion(state,limitations=['Bounded to the selected input']),(False,False))
        assert effects==[{'object':'interpretations','action':'append','target':'interpretations[0]',
                         'investigation_id':state['investigations'][0]['id'],'changed_fields':['limitations']}]
        sub,files=opinion(state,limitations=['Bounded to the selected input'])
        sub['interpretations'].extend(opinion(state)[0]['interpretations'])
        effects=validate(sub,files,(False,False))
        assert [effect['target'] for effect in effects]==['interpretations[0]','interpretations[1]']
        assert [effect['changed_fields'] for effect in effects]==[['limitations'],['limitations']]
        assert validate(*opinion(state),(True,False))[0]['action']=='unchanged'
        assert validate({'rationale':'Directed question answered','stop':{'reason':'bounded_completed','rationale':'The selected local question is answered.'}},
                        {},(False,False))==[{'object':'run','action':'stop','reason':'bounded_completed'}]
        return stop(state)
    e,repo=engine_for(tmp_path,[start,inspect,finish])
    state=e.start(repo)
    assert len(state.experiments)==len(state.interpretations)==len(state.knowledge)==1
    assert state.usage=={'agent_calls':3,'experiments':1}


def test_source_only_answer_and_exact_noop_keep_cost_without_revisions(tmp_path):
    def answer(state):
        q=state['investigations'][0]['id']
        return {'rationale':'Existing sources explain this local branch',
            'investigations':[{'id':q,'disposition':'explained'}],
            'interpretations':[dict(investigation_id=q,source_ids=['code','doc'],conclusion='explained',
                                    defect_claim=None,counterevidence=['Capacity branch handles the stated case'],rationale='The boundary branch is directly visible in the cited source')]},{}
    seen=[]
    def duplicate(state):
        assert 'reselection' in operation_summary(e.state,e.root)
        seen.append(state)
        return answer(state)
    def finish(state):
        assert state['current_submission']['no_change']
        assert state['investigations']==seen[0]['investigations']
        assert state['interpretations']==seen[0]['interpretations']
        from consensus_assurance.workflow.audit import prompt
        feedback=json.loads(prompt(e,'').split('Current work (controller records):\n')[1])
        assert feedback['no_change'] and feedback['allocation']['seconds']>0
        assert not feedback['questions']
        assert feedback['allocation']['agent_calls']==e.config.budget.agent_calls-state['usage']['agent_calls']
        assert 'already retained' in feedback['next'] and 'still consumed' in feedback['next']
        assert 'do not repeat closing submissions' in feedback['next'] and 'reselection' in feedback
        return stop(state)
    e,repo=engine_for(tmp_path,[first,answer,duplicate,finish])
    state=e.start(repo)
    assert state.usage['agent_calls']==4 and state.usage.get('experiments',0)==0
    assert len(list((e.root/'submissions').glob('*/raw.json')))==3


@pytest.mark.parametrize('claim,disposition,gap', [
    ('refuted','active',False), ('asserted','active',True),
    (None,'active',False), ('unresolved','paused',True),
])
def test_reselection_does_not_gate_research_on_the_previous_judgment(tmp_path,claim,disposition,gap):
    def start(state):
        sub,files=first(state)
        sub['interpretations']=[dict(investigation_id='@q',source_ids=['code'],conclusion='unresolved',
            defect_claim='asserted',rationale='An initial scoped suspicion, subject to further source inspection')]
        if gap:sub['gaps']=[dict(investigation_id='@q',question='Does the producer establish the necessary input?')]
        return sub,files
    def revise(state):
        q=state['investigations'][0]['id']
        change=dict(id=q,disposition=disposition)
        if disposition=='paused':change['resume_conditions']=['An applicable producer path is located']
        return {'rationale':'Update the scoped judgment after further source inspection',
            'investigations':[change], 'interpretations':[dict(investigation_id=q,source_ids=['code'],
                conclusion='unresolved',defect_claim=claim,rationale='Current source account; no mechanical comparison claimed')]},{}
    def finish(state):
        summary=operation_summary(e.state,e.root)
        assert summary['reselection']['questions'][0]['id']==state['investigations'][0]['id']
        assert bool(summary['necessary_gaps'])==gap
        assert state['investigations'][0]['disposition']==disposition
        assert state['interpretations'][-1]['defect_claim']==claim and len(state['interpretations'])==2
        assert not state['experiments'] and 'confirmed' not in summary
        return stop(state)
    e,repo=engine_for(tmp_path,[start,revise,finish])
    e.start(repo)


def test_necessary_gap_preserves_partial_answers_resolution_and_reopening(tmp_path):
    def start(state):
        sub,files=combined(state)
        sub['gaps']=[dict(investigation_id='@q',question='Does normal initialization reach this premise?')]
        return sub,files
    def child(state):
        q=state['investigations'][0]['id']
        return {'rationale':'Independent local child', 'investigations':[dict(ref='@child',parent_id=q,
            question='What does the return expression compute?',source_ids=['code'],disposition='explained')],
            'interpretations':[dict(investigation_id='@child',source_ids=['code'],conclusion='explained',defect_claim=None,
                rationale='The actual expression returns zero at capacity')]},{}
    def answer(state):
        gap=state['investigations'][0]['gaps'][0]['id']
        return opinion(state,answers={gap:dict(resolved=True,
            explanation='The cited local contract allows precisely this input; no distributed prefix is claimed')})
    seen=[]
    def partial(state):
        assert open_gaps(e.state,e.state.investigations[0].id)
        seen.append(e.state.model_copy(deep=True))
        gap=state['investigations'][0]['gaps'][0]['id']
        return opinion(state,answers={gap:dict(resolved=False,
            explanation='The initializer was located; the actual caller condition still needs inspection. '*8)})
    def omit_partial(state):
        assert open_gaps(e.state,e.state.investigations[0].id)
        return opinion(state,rationale='Preserve partial producer research while inspecting the unchanged observation')
    def resolve(state):
        assert open_gaps(e.state,e.state.investigations[0].id)
        assert not state['interpretations'][-1]['answers']
        response=operation_summary(e.state,e.root)['necessary_gaps'][0]['response']
        full_response=next(iter(state['interpretations'][-2]['answers'].values()))
        assert response['explanation']==excerpt(full_response['explanation']) and not response['resolved']
        view=json.loads((e.root/'research.json').read_text())
        assert view['investigations'][0]['open_gaps'][0]['response']==response
        locator=view['investigations'][0]['open_gaps'][0]['response_record']
        saved=json.loads((e.root/locator['path']).read_text())
        account=next(i for i in saved[locator['collection']] if i['id']==locator['id'])
        assert full_response in account['answers'].values()
        from consensus_assurance.reporting.report import render_report
        report=render_report(e.state,e.root).read_text().split('Fixed experiment `',1)[0]
        assert 'Latest response (gap remains open): '+full_response['explanation'] in report
        return answer(state)
    def omit(state):
        assert not open_gaps(e.state,e.state.investigations[0].id)
        return opinion(state,rationale='Review the same return without revising the saved premise answer')
    def reopen(state):
        q=state['investigations'][0]
        assert not open_gaps(e.state,q['id']) and not state['interpretations'][-1]['answers']
        return {'rationale':'A newly inspected caller restriction invalidates the earlier answer',
            'interpretations':[dict(investigation_id=q['id'],source_ids=['doc'],conclusion='unresolved',defect_claim=None,
                answers={q['gaps'][0]['id']:dict(resolved=False,
                    explanation='The earlier contract account did not establish the actual caller condition')},
                rationale='Preserve the observation while reopening its necessary premise')]},{}
    def reanswer(state):
        assert open_gaps(e.state,state['investigations'][0]['id'])
        return answer(state)
    def duplicate(state):
        assert not open_gaps(e.state,state['investigations'][0]['id'])
        return answer(state)
    def finish(state):
        assert state['current_submission']['no_change']
        return stop(state)
    e,repo=engine_for(tmp_path,[start,opinion,child,partial,omit_partial,resolve,omit,reopen,reanswer,duplicate,finish])
    state=e.start(repo)
    assert not open_gaps(state,state.investigations[0].id)
    assert open_gaps(seen[0],seen[0].investigations[0].id)
    assert state.investigations[0].disposition=='active'
    assert len(state.experiments)==1
    answers=[i.answers for i in state.interpretations if i.answers]
    assert [next(iter(a.values())).resolved for a in answers]==[False,True,False,True]
    assert answers[1]==answers[3] and answers[0]!=answers[2]
    assert [c for c in state.checks if c.action=='experiment']==[c for c in seen[0].checks if c.action=='experiment']


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


def research_case(state, protected=False, supplied=False):
    source=Path('tests/fixtures/research_protocol.py').read_text()
    sources=[dict(id='code',file='target.py',start_line=1,end_line=len(source.splitlines()),kind='code_observation'),
             dict(id='doc',file='README.md',start_line=1,end_line=1,kind='document_statement')]
    setup="ticket=(0,0)\nworker.pending.add(ticket)\nworker.reported.add(ticket)" if supplied else 'ticket=worker.begin()\nworker.report(ticket)'
    code=f'''import json
from target import Worker
worker=Worker(protected={protected!r})
{setup}
print('CA_EVENT '+json.dumps(dict(event='admitted',operation='one',epoch=worker.epoch)))
print('CA_EVENT '+json.dumps(dict(event='result',operation='one',epoch=worker.epoch,allowed=worker.allowed(ticket),finished=ticket in worker.finished)))
'''
    request=dict(investigation_id='@q',harness_path='check.py',source_ids=['code','doc'],
        scope={'description':'Notification and completion in one authority context','assumptions':['Supplied pending and reported sets'] if supplied else []},
        prefix='Supplied pending/report sets; no production history' if supplied else 'Construct Worker, call begin and report; observe allowed and finished',
        requirement='For a current admitted ticket, allowed implies finished',responsibility='The fixture caller contract explicitly separates report from finish',
        anchors=[dict(material_id='code',symbol='Worker.allowed',start_line=33,end_line=35)],
        prerequisites=[dict(alias='start',event='admitted')],
        comparisons=[dict(event='result',identity_fields=['operation','epoch'],admission_alias='start',
            antecedent={'field':'allowed','value':True},assertion={'field':'finished','value':True})])
    if state.get('investigations'):
        request['investigation_id']=state['investigations'][0]['id']
        request['previous_id']=state['experiments'][-1]['id']
        request['revision_reason']='Replace supplied state with the actual initializer and producer prefix'
        return {'rationale':'Investigate the registered missing history','experiment':request},{'check.py':code}
    sub={'rationale':'Separate produced notification from established completion','sources':sources,
        'knowledge':[dict(ref='@fact',kind='fact',statement='A recorded notification establishes completion',conditions='Current ticket',source_ids=['code','doc'])],
        'investigations':[dict(ref='@q',question='Does the decision guard require actual completion?',source_ids=['code','doc'],
            hypothesis='Notification may be consumed as completion',discriminator='Compare a real producer prefix and protected path',
            knowledge=[dict(entry_id='@fact',revision=1)]),
            dict(ref='@later',question='Does an authority transition retire the earlier ticket?',source_ids=['code'],knowledge=[dict(entry_id='@fact',revision=1)])],
        'gaps':[dict(investigation_id='@q',question='Was the critical notification established by actual producers?')],
        'experiment':request}
    return sub,{'check.py':code}


def test_conditional_probe_real_history_knowledge_correction_and_reuse(tmp_path):
    def initial(state):
        sub,files=research_case(state,supplied=True)
        sub['knowledge'][0].update(kind='behavior',statement='Both guard branches grant after report')
        sub['knowledge'].extend(dict(kind='behavior',statement=statement,conditions='Serialized calls',source_ids=['code'])
            for statement in ('begin allocates a ticket','finish records a pending ticket','advance clears the pending set'))
        sub['experiment']['knowledge']=[dict(entry_id='@fact',revision=1)]
        sub['investigations'][1]['knowledge']=[]
        return sub,files
    def prefix(state):
        sub,files=research_case(state)
        sub['experiment']['knowledge']=[dict(entry_id=state['knowledge'][0]['id'],revision=1)]
        return sub,files
    def branch_control(state):
        sub,files=research_case(state,protected=True)
        sub['experiment']['revision_reason']='Observe the legitimate protected guard branch using the same actual producer prefix'
        sub['interpretations']=opinion(state,knowledge=[dict(entry_id=state['knowledge'][0]['id'],revision=1)],
            rationale='The reporting branch grants before finish; whether this generalizes to the other branch remains to be checked')[0]['interpretations']
        return sub,files
    def correct(state):
        q,later=state['investigations']
        fact=state['knowledge'][0]
        check=next(c for c in state['checks'] if c.get('experiment_id')==state['experiments'][-1]['id'])
        sub,files=opinion(state,conclusion='holds',knowledge=[dict(entry_id=fact['id'],revision=2)],
            answers={q['gaps'][0]['id']:dict(explanation='Fresh executions invoke real begin and report in the same context',resolved=True)},
            rationale='The protected branch requires finish; the earlier general statement about both branches was inaccurate')
        sub['knowledge']=[dict(id=fact['id'],kind='behavior',
            statement='The reporting branch grants after report; the protected branch requires finish',
            conditions='Current admitted ticket; report may precede finish',source_ids=['code','doc'],
            executions={check['id']:[1]},changed_premise='Grant after report applies only to the reporting branch',
            affected_uses=[q['id'],state['experiments'][1]['id'],state['interpretations'][0]['id']])]
        corrected.append(sub['knowledge'][0])
        return sub,files
    corrected=[]
    def duplicate(state):
        summary=operation_summary(e.state,e.root)
        correction=summary['knowledge_corrections'][0]
        entry=state['knowledge'][0]
        assert (correction['id'],correction['revision'],correction['previous_revision'])==(entry['id'],2,1)
        assert correction['changed_premise']==corrected[0]['changed_premise']
        assert correction['recorded_uses']==entry['history'][0]['recorded_uses']
        assert correction['affected_uses']==corrected[0]['affected_uses']
        assert correction['record']=={'path':'state.json','collection':'knowledge','id':entry['id']}
        assert correction['affected_use_locations']==[
            {'id':id,'investigation_id':state['investigations'][0]['id'],
             'latest_interpretation':{'path':'state.json','collection':'interpretations','id':state['interpretations'][-1]['id']}}
            for id in corrected[0]['affected_uses']]
        assert summary['necessary_gaps'] and len(summary['knowledge_corrections'])==1
        return {'rationale':'Repeat the same effective correction','knowledge':corrected},{}
    def global_choice(state):
        assert state['current_submission']['no_change']
        summary=operation_summary(e.state,e.root)
        assert 'knowledge_corrections' not in summary
        assert summary['reselection']['target']['repo']==str(repo)
        assert {q['id'] for q in summary['reselection']['questions']}=={q['id'] for q in state['investigations']}
        assert summary['open_work_index']=='research.json' and summary['allocation']['agent_calls']>0
        index=json.loads((e.root/'research.json').read_text())
        entry=next(k for k in index['knowledge'] if k['id']==corrected[0]['id'])
        assert entry['revision']==2 and entry['last_correction']['affected_uses']==corrected[0]['affected_uses']
        assert entry['statement']==corrected[0]['statement'] and entry['executions']
        q=state['investigations'][1]
        assert not q['gaps'] and not q['knowledge']
        return {'rationale':'Select the independent authority question, not another guard variant',
            'investigations':[dict(id=q['id'],disposition='explained')],
            'interpretations':[dict(investigation_id=q['id'],source_ids=['code'],conclusion='explained',defect_claim=None,
                rationale='advance changes epoch and clears pending tickets, protecting against old-ticket reuse')]},{}
    def local_lead(state):
        return {'rationale':'A separate local completion responsibility becomes worth tracing',
            'investigations':[dict(question='Can a reported ticket be explicitly finished before authority changes?',
                source_ids=['code'],knowledge=[dict(entry_id=state['knowledge'][0]['id'],revision=2)],
                discriminator='Trace the actual finish producer, independent of whether report alone grants')]},{}
    e,repo=engine_for(tmp_path,[initial,prefix,branch_control,correct,duplicate,global_choice,local_lead,stop])
    e.config.directed_question=None
    (repo/'target.py').write_text(Path('tests/fixtures/research_protocol.py').read_text())
    (repo/'README.md').write_text('Calls are serialized; report may precede finish; allowed requires completion of a current ticket.\n')
    state=e.start(repo)
    assert len(state.experiments)==3, state.current_submission
    assert state.knowledge[0].revision==2 and len(state.knowledge[0].history)==1
    assert all(k.revision==1 and not k.history for k in state.knowledge[1:])
    assert not open_gaps(state,state.investigations[1].id)
    assert open_gaps(state,state.investigations[0].id)
    assert state.investigations[2].knowledge[0].revision==2
    assert all(q.parent_id is None for q in state.investigations)
    assert state.knowledge[0].history[0]['statement']=='Both guard branches grant after report'
    assert state.experiments[1].basis.knowledge[0].revision==1 and state.interpretations[0].knowledge[0].revision==1
    assert len(state.interpretations)==3 and state.agent_session_id=='fixture-session'
    assert state.experiments[0].basis.scope.assumptions
    assert not state.experiments[1].basis.scope.assumptions
    assert [assessment(state,e.root,a,next(c for c in state.checks if c.experiment_id==a.id))['outcome'] for a in state.experiments]==['violated','violated','holds']


@pytest.mark.parametrize('protected,expected',[(False,'violated'),(True,'holds')])
def test_same_actual_measurement_distinguishes_bug_and_control(tmp_path,protected,expected):
    e,repo=engine_for(tmp_path,[lambda state:research_case(state,protected),stop])
    (repo/'target.py').write_text(Path('tests/fixtures/research_protocol.py').read_text())
    (repo/'README.md').write_text('report may precede finish; allowed requires completed current work.\n')
    state=e.start(repo)
    assert state.experiments,state.current_submission
    a=state.experiments[0]
    c=next(c for c in state.checks if c.experiment_id==a.id)
    result=assessment(state,e.root,a,c)
    assert result['outcome']==expected
    from consensus_assurance.workflow.observations import compare_events
    assert compare_events([],a.basis.comparisons[0],a.basis.harness.prerequisites)['outcome']=='unknown'
    fabricated=[dict(event='admitted',operation='one',epoch=0),dict(event='result',operation='one',epoch=0,allowed=False,finished=False)]
    if not protected:
        assert compare_events(fabricated,a.basis.comparisons[0],a.basis.harness.prerequisites)['outcome']!=expected


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
        assert 'knowledge_corrections' not in operation_summary(engine.state,engine.root)
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


def test_knowledge_correction_without_uses_does_not_infer_dependencies(tmp_path):
    def start(state):
        sub,files=first(state)
        sub['knowledge']=[dict(kind='behavior',statement='The boundary preserves the input',
            conditions='Capacity input',source_ids=['code'])]
        return sub,files
    def correct(state):
        assert 'knowledge_corrections' not in operation_summary(e.state,e.root)
        change=dict(id=state['knowledge'][0]['id'],kind='behavior',statement='The boundary returns zero',
            conditions='Capacity input',source_ids=['code'],changed_premise='Returning zero does not preserve capacity input')
        return {'rationale':'Correct a behavior then clarify wording in the same operation',
            'knowledge':[change,{**change,'conditions':'Input equals capacity','changed_premise':''}]},{}
    def unrelated(state):
        correction=operation_summary(e.state,e.root)['knowledge_corrections'][0]
        assert not correction['recorded_uses'] and not correction['affected_uses']
        assert correction['affected_use_locations']==[]
        assert (correction['revision'],correction['previous_revision'])==(3,1)
        assert not state['investigations'][0]['gaps'] and state['investigations'][0]['version']==1
        assert state['knowledge'][0]['history'][0]['source_ids']==['code']
        return {'rationale':'Add an independent behavior', 'knowledge':[dict(kind='behavior',
            statement='A below-capacity input is incremented',conditions='Input below capacity',source_ids=['code'])]},{}
    def finish(state):
        assert 'knowledge_corrections' not in operation_summary(e.state,e.root)
        return stop(state)
    e,repo=engine_for(tmp_path,[start,correct,unrelated,finish])
    e.start(repo)


def test_knowledge_correction_traces_old_root_and_derived_revisions_and_accepts_later_impacts(tmp_path):
    dependency='The stored return preserves the admitted value only for the cited capacity call. ' * 6
    def initial(state):
        sub,files=combined(state)
        sub['knowledge']=[dict(ref='@premise',kind='behavior',statement='The boundary preserves its input',
            conditions='Capacity input',source_ids=['code']),
            dict(ref='@fact',kind='fact',statement='The boundary retains the admitted value',
                conditions='Capacity input',source_ids=['code'],knowledge=[dict(entry_id='@premise',revision=1,assertion=dependency)])]
        sub['investigations'][0]['knowledge']=[dict(entry_id='@fact',revision=1)]
        sub['experiment']['knowledge']=[dict(entry_id='@fact',revision=1)]
        sub['interpretations']=[dict(investigation_id='@q',source_ids=['code'],conclusion='explained',
            defect_claim='refuted',rationale='The earlier account treats the boundary as preserving its input',
            knowledge=[dict(entry_id='@fact',revision=1)])]
        return sub,files
    def unrelated(state):
        request,files=experiment('@other')
        fact=state['knowledge'][1]
        index=json.loads((e.root/'research.json').read_text())
        preview=next(k for k in index['knowledge'] if k['id']==fact['id'])
        assert preview['knowledge'][0]['assertion']==excerpt(dependency)
        assert fact['knowledge'][0]['assertion']==dependency
        request['knowledge']=[dict(entry_id=fact['id'],revision=2)]
        return {'rationale':'Record a separately sourced bound and explore its return value',
            'knowledge':[dict(id=state['knowledge'][0]['id'],kind='behavior',statement='The boundary preserves its input',
                conditions='Capacity input',source_ids=['code','doc']),
                dict(id=fact['id'],kind='fact',statement='The return remains within the documented bounds',
                conditions='Legal input and positive capacity',source_ids=['code','doc'],knowledge=[],
                changed_premise='The bounded return is sourced directly, without assuming input preservation')],
            'investigations':[dict(ref='@other',question='What value does the boundary return?',source_ids=['code'],
                knowledge=[dict(entry_id=fact['id'],revision=2)])],
            'experiment':request},files
    retained={}
    def correct(state):
        assert not any(q['gaps'] for q in state['investigations'])
        assert state['knowledge'][0]['revision']==2
        entry=json.loads((e.root/'research.json').read_text())['knowledge'][0]
        expected=[state['investigations'][0]['id'],state['experiments'][0]['id'],state['interpretations'][0]['id']]
        assert entry['use_paths']=={id:[dict(entry_id=k['id'],revision=1,assertion=excerpt(dependency) if n==0 else '')
            for n,k in enumerate(state['knowledge'])] for id in expected}
        retained['interpretations']=state['interpretations']
        retained['checks']={c['id']:(e.root/'logs'/c['id']/'check.json').read_bytes()
            for c in state['checks'] if c.get('experiment_id')}
        retained['correction']=dict(id=state['knowledge'][0]['id'],kind='behavior',statement='The boundary returns zero',
            conditions='Capacity input',source_ids=['code','doc'],changed_premise='Zero does not preserve the capacity input',
            affected_uses=[state['investigations'][0]['id']])
        return {'rationale':'Correct the earlier premise without revising its conclusion automatically',
            'knowledge':[retained['correction']]},{}
    def supplement(state):
        assert state['knowledge'][0]['revision']==3
        assert len(state['investigations'][0]['gaps'])==1
        retained['correction']['affected_uses'] += [state['experiments'][0]['id'],state['interpretations'][0]['id']]
        return {'rationale':'The same corrected premise also affects the recorded experiment and interpretation',
            'knowledge':[retained['correction']]},{}
    def finish(state):
        summary=operation_summary(e.state,e.root)
        old,current=state['investigations']
        actual=summary['latest_actual_execution']
        assert actual['investigation_id']==current['id']
        assert [q['id'] for q in summary['questions']]==[old['id']]
        correction=summary['knowledge_corrections'][0]
        expected=[old['id'],state['experiments'][0]['id'],state['interpretations'][0]['id']]
        assert correction['recorded_uses']==expected
        locations=correction['affected_use_locations']
        assert [value['id'] for value in locations]==expected
        for value in locations:
            assert value['investigation_id']==old['id']
            assert value['knowledge_path']==[dict(entry_id=k['id'],revision=1,assertion=excerpt(dependency) if n==0 else '')
                for n,k in enumerate(state['knowledge'])]
            locator=value['latest_interpretation']
            saved=json.loads((e.root/locator['path']).read_text())
            opinion=next(i for i in saved[locator['collection']] if i['id']==locator['id'])
            assert opinion==retained['interpretations'][0]
        assert state['interpretations']==retained['interpretations']
        assert old['disposition']==current['disposition']=='active' and not current['gaps']
        fact=state['knowledge'][1]
        assert fact['revision']==2 and not fact['knowledge']
        assert fact['history'][0]['knowledge']==[dict(entry_id=state['knowledge'][0]['id'],revision=1,assertion=dependency)]
        assert state['experiments'][0]['basis']['knowledge']==[dict(entry_id=fact['id'],revision=1,assertion='')]
        assert state['experiments'][1]['basis']['knowledge']==[dict(entry_id=fact['id'],revision=2,assertion='')]
        assert summary['necessary_gaps'] and all(g['investigation_id']==old['id'] for g in summary['necessary_gaps'])
        assert 'reselection' in summary and 'confirmed' not in summary
        assert all((e.root/'logs'/id/'check.json').read_bytes()==raw for id,raw in retained['checks'].items())
        return {'rationale':'Repeat the already retained correction and impact account',
            'knowledge':[retained['correction']]},{}
    def repeated(state):
        assert state['current_submission']['no_change'] and state['knowledge'][0]['revision']==4
        assert len(state['investigations'][0]['gaps'])==2
        return stop(state)
    e,repo=engine_for(tmp_path,[initial,unrelated,correct,supplement,finish,repeated])
    state=e.start(repo)
    assert state.usage['experiments']==2 and len(state.interpretations)==1


def test_navigation_keeps_evidence_references_and_marks_long_prose_without_mutating_records(tmp_path):
    from consensus_assurance.core.types import KnowledgeEntry
    from consensus_assurance.workflow.research import current_view, preview
    engine,repo=engine_for(tmp_path,[stop])
    state=engine.start(repo,plan_only=True)
    entry=KnowledgeEntry(id='projection-entry',kind='behavior',operation_id='projection',
        statement='A bounded observation with several supporting records',
        conditions='The observation applies only within its recorded invocation interval. '*12,
        source_ids=[f'source-{i}' for i in range(8)],executions={f'receipt-{i}':[i] for i in range(4)})
    state.knowledge.append(entry)
    engine.store.save(state,'projection_fixture')
    saved=(engine.root/'state.json').read_bytes()
    before=state.model_dump(mode='json')
    current=current_view(state,engine.root)
    summary=operation_summary(state,engine.root)
    item=current['knowledge'][0]
    assert item['source_ids']==entry.source_ids and item['executions']==entry.executions
    assert '[preview:' in item['conditions'] and 'characters omitted; see full record]' in item['conditions']
    assert item['conditions'].count('[preview:')==1 and preview(item)==item
    for item in (item,current['reselection']['knowledge'][0],summary['reselection']['knowledge'][0]):
        locator=item['record']
        complete=json.loads((engine.root/locator['path']).read_text())[locator['collection']]
        assert item['view']=='preview'
        assert next(record for record in complete if record['id']==locator['id'])==entry.model_dump(mode='json')
    assert state.model_dump(mode='json')==before and (engine.root/'state.json').read_bytes()==saved
