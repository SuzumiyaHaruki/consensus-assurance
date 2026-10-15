import json
import shutil
import pytest
from types import SimpleNamespace
from audit_support import engine_for, combined, experiment, opinion, stop
from consensus_assurance.core.types import CheckRun, ExecutionStatus
from consensus_assurance.workflow.research import execution_cost, costs
from consensus_assurance.workflow.experiments import assessment
from consensus_assurance.reporting.report import render_report


def test_costs_keep_missing_data_and_do_not_double_count_children(tmp_path):
    c=CheckRun(id='parent',action='experiment',cwd=str(tmp_path),snapshot_id='fixture',
        started_at='2026-10-04T00:00:01+00:00',ended_at='2026-10-04T00:00:05.300000+00:00',
        parameters={'action_seconds':28.71})
    old=c.model_copy(update={'id':'old','parameters':{}})
    child=c.model_copy(update={'id':'child','action':'cargo_seed_copy'})
    state=SimpleNamespace(checks=[c,old,child,c.model_copy(deep=True)],usage={},elapsed_seconds=80)
    result=costs(state)
    assert result['target_executions']==2 and result['process_seconds']==8.6
    assert result['action_seconds']==28.71 and result['unrecorded_action_ids']==['old']
    for invalid in (None,-1,float('inf'),float('nan'),True,'28.71'):
        assert execution_cost(c.model_copy(update={'parameters':{'action_seconds':invalid},'started_at':'invalid'}))=={'process_seconds':None,'action_seconds':None}


@pytest.mark.parametrize('outcome',['unknown','holds'])
def test_report_distinguishes_unchecked_and_opposing_mechanical_results(tmp_path,outcome):
    def start(state):
        value,files=combined(state)
        if outcome=='unknown':
            value['experiment'].update(requirement=None,comparisons=[])
        else:
            value['experiment']['comparisons'][0]['assertion']={'field':'value','value':0}
        return value,files
    e,repo=engine_for(tmp_path,[start,lambda s:opinion(s,defect_claim='asserted'),stop])
    state=e.start(repo)
    assert len(state.interpretations)==1
    text=render_report(state,e.root).read_text()
    assert ('Interpretation differs from the mechanical result' in text)==(outcome=='holds')
    assert ('mechanical comparison is undetermined, not an opposing conclusion' in text)==(outcome=='unknown')
    assert 'Current model defect claim: defect asserted' in text and 'confirmed' not in text
    assert 'Mechanical results evaluate declared predicates' in text
    assert 'not provider request count' in text and 'excludes Agent local exploratory checks' in text
    assert f'### {state.investigations[0].question}' in text
    assert state.interpretations[0].rationale in text


@pytest.mark.parametrize('claim,label',[
    ('refuted','defect claim refuted within the stated scope'), ('unresolved','unresolved'), (None,'no explicit defect claim submitted')])
def test_report_uses_actual_observations_and_preserves_opinion_history(tmp_path,claim,label):
    def start(state):
        value,files=combined(state)
        value['gaps']=[dict(investigation_id='@q',question=question) for question in
            ['Which caller contract applies?', 'Was the producer history legal?']]
        return value,files
    def initial(state):
        return opinion(state,defect_claim='asserted',rationale='Compare the actual return. The initial model alleges a defect',
            counterevidence=['The documented input bound may exclude this caller'],limitations=['Only one call was observed'],
            answers={state['investigations'][0]['gaps'][0]['id']:dict(explanation='Initial contract reading',resolved=True)})
    def correction(state):
        value,files=opinion(state,experiment_id=None,conclusion='conditional',rationale='Caller history remains unestablished',
            counterevidence=['The actual caller duty excludes the alleged general obligation'],
            limitations=['No broader consensus conclusion follows'],
            answers={state['investigations'][0]['gaps'][0]['id']:dict(resolved=claim!='refuted',
                explanation='The earlier answer did not establish the actual caller condition' if claim=='refuted' else 'The cited local contract controls this call')},
            defect_claim=claim)
        if claim is None:
            value['interpretations'][0].pop('executions')
        return value,files
    e,repo=engine_for(tmp_path,[start,initial,correction,stop]);s=e.start(repo)
    before=s.model_dump(mode='json')
    text=render_report(s,e.root).read_text()
    current,execution=text.split('Fixed experiment `',1)
    execution,history=execution.split('Interpretation history:',1)
    for value in [s.interpretations[-1].rationale,*s.interpretations[-1].counterevidence,
                  *s.interpretations[-1].limitations,*[v.explanation for v in s.interpretations[-1].answers.values()]]:
        assert value in current and text.count(value)==1
    if claim=='refuted':
        assert 'gap remains open:' in current and 'Which caller contract applies?' in current
    assert current.count('Was the producer history legal?')==1
    assert not {'counterevidence','limitations'} & s.investigations[0].model_dump().keys()
    assert 'Question counterevidence:' not in text and 'Question boundaries:' not in text
    for value in [s.interpretations[0].rationale,*s.interpretations[0].counterevidence,*s.interpretations[0].limitations]:
        assert value not in text
    saved_history=json.loads((e.root/'state.json').read_text())['interpretations']
    assert saved_history==[i.model_dump(mode='json') for i in s.interpretations]
    assert f'[{s.interpretations[0].id}](state.json) → [{s.interpretations[1].id}](state.json)' in history
    assert f'model claim asserted → {claim or "none"}' in history
    assert 'changed fields:' in history and 'rationale' in history and 'source_ids' not in history
    assert 'historical interpretation; the question has a later account' in execution
    assert all(i.rationale not in execution for i in s.interpretations)
    assert [i.defect_claim for i in s.interpretations]==['asserted',claim]
    claims,other=text.split('## Explicit model defect claims (subject to independent verification)',1)[1].split('## Other research results',1)
    assert s.investigations[0].question not in claims and s.investigations[0].question in other
    assert f'Current model defect claim: {label}' in text
    assert text.count('### ')==1
    assert 'Compare the actual return' in saved_history[0]['rationale']
    assert 'confirmed' not in text and 'declared predicate does not hold' in text
    check=next(c for c in s.checks if c.experiment_id)
    citations=assessment(s,e.root,s.experiments[0],check)['interpretation_citations']
    assert citations['historical_count']==1
    assert [i['id'] for i in citations['current']]==([s.interpretations[-1].id] if claim is not None else [])
    assert ('Other current question interpretations explicitly citing this receipt' in execution)==(claim is not None)
    observation=f'logs/{check.id}/observations.json'
    assert '[code](state.json)' in current and '[doc](state.json)' in current
    assert (f'logs/{check.id}/check.json' in current)==(claim is not None)
    assert (observation in current)==(claim is not None)
    assert ('event indices [1]' in current)==(claim is not None)
    assert ('No execution receipt explicitly cited by this interpretation' in current)==(claim is None)
    assert json.loads((e.root/observation).read_text())['events'][1]['value']==0
    assert s.model_dump(mode='json')==before
    clone=tmp_path/'moved';shutil.copytree(e.root,clone)
    original=e.root.with_name('unavailable');e.root.rename(original)
    from consensus_assurance.adapters.storage.files import Store
    saved=Store(clone).load()
    assert saved.interpretations==s.interpretations
    moved=render_report(saved,clone).read_text()
    assert observation in moved and json.loads((clone/observation).read_text())['events'][1]['value']==0
    assert str(original) not in moved and str(e.root) not in moved
    import re
    for link in re.findall(r'\]\(([^)]+)\)',moved):assert (clone/link).is_file(),link


@pytest.mark.parametrize('superseded',[False,True])
def test_other_experiment_receipt_citations_do_not_change_direct_assessment(tmp_path,superseded):
    before={}
    def start(state):
        value,files=combined(state)
        value['gaps']=[dict(investigation_id='@q',question='Was the producer history legal?')]
        return value,files
    def downstream(state):
        fixed=e.state.experiments[0]
        check=next(c for c in e.state.checks if c.experiment_id==fixed.id)
        before.update(assessment(e.state,e.root,fixed,check))
        request,files=experiment('@other')
        return {'rationale':'Inspect a related local consequence',
            'investigations':[dict(ref='@other',question='What does this separate local call establish?',source_ids=['code'])],
            'experiment':request},files
    def cite(state):
        return opinion(state,executions={c['id']:[1] for c in state['checks'] if c.get('experiment_id')},
            joint_history='These are independent calls to the same stateless function, not one distributed history')
    def revise(state):
        return opinion(state,experiment_id=None,executions={},conclusion='explained',
            rationale='A narrower source-only account supersedes the measured account')
    e,repo=engine_for(tmp_path,[start,downstream,cite,*([revise] if superseded else []),stop])
    s=e.start(repo)
    fixed=s.experiments[0]
    check=next(c for c in s.checks if c.experiment_id==fixed.id)
    after=assessment(s,e.root,fixed,check)
    assert after['interpretation_id'] is None
    assert after['gap_ids'] and 'no interpretation directly attributed' in str(after['blockers'])
    assert {k:v for k,v in after.items() if k!='interpretation_citations'}=={
        k:v for k,v in before.items() if k!='interpretation_citations'}
    citations=after['interpretation_citations']
    assert citations['historical_count']==int(superseded)
    assert citations['current']==([] if superseded else [dict(id=s.interpretations[0].id,
        investigation_id=s.investigations[1].id,experiment_id=s.experiments[1].id,event_indices=[1])])
    text=render_report(s,e.root).read_text().split('### '+s.investigations[1].question)[0]
    assert ('Other current question interpretations explicitly citing this receipt' in text)==(not superseded)
    assert ('Historical interpretations explicitly citing this receipt: 1' in text)==superseded
    assert 'No current explicit defect assertion' in text
