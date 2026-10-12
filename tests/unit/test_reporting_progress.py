import json
import shutil
import pytest
from types import SimpleNamespace
from audit_support import engine_for, combined, opinion, stop
from consensus_assurance.core.types import CheckRun, ExecutionStatus
from consensus_assurance.workflow.research import execution_cost, costs
from consensus_assurance.reporting.chinese import render_report


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


@pytest.mark.parametrize('claim,label',[
    ('refuted','当前疑点已否定'), ('unresolved','尚不能判断'), (None,'未提交缺陷判断')])
def test_report_uses_actual_observations_and_preserves_opinion_history(tmp_path,claim,label):
    def initial(state):return opinion(state,defect_claim='asserted',rationale='Compare the actual return. The initial model alleges a defect')
    def correction(state):
        return opinion(state,conclusion='conditional',rationale='Caller history remains unestablished',
                       **({'defect_claim':claim} if claim else {}))
    e,repo=engine_for(tmp_path,[combined,initial,correction,stop]);s=e.start(repo)
    before=s.model_dump(mode='json')
    text=render_report(s,e.root).read_text()
    assert 'Caller history remains unestablished' in text and 'The initial model alleges a defect' in text
    assert [i.defect_claim for i in s.interpretations]==['asserted',claim]
    claims,other=text.split('## 模型明确主张的缺陷（待人工核验）',1)[1].split('## 其他研究结果',1)
    assert s.investigations[0].question not in claims and s.investigations[0].question in other
    assert f'当前模型缺陷判断：{label}' in text
    assert text.count('### ')==1
    assert 'Compare the actual return' in text
    assert '反例见证未确认' in text and '所声明比较条件不成立' in text
    check=next(c for c in s.checks if c.experiment_id)
    observation=f'logs/{check.id}/observations.json'
    assert observation in text and json.loads((e.root/observation).read_text())['events'][1]['value']==0
    assert s.model_dump(mode='json')==before
    clone=tmp_path/'moved';shutil.copytree(e.root,clone)
    original=e.root.with_name('unavailable');e.root.rename(original)
    from consensus_assurance.adapters.storage.files import Store
    saved=Store(clone).load()
    moved=render_report(saved,clone).read_text()
    assert observation in moved and json.loads((clone/observation).read_text())['events'][1]['value']==0
    assert str(original) not in moved and str(e.root) not in moved
    import re
    for link in re.findall(r'\]\(([^)]+)\)',moved):assert (clone/link).is_file(),link
