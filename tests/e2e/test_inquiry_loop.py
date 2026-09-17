import json
import os
from pathlib import Path
import pytest
from coverage_support import CoverageAgent,add_coverage_materials
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.adapters.storage.files import Store
from consensus_assurance.reporting.chinese import render_report


def setup(tmp_path,prepared,wrong=False,weak=False,tlc=None):
    repo,_,_,responses=prepared;add_coverage_materials(repo)
    config=Config(implementation='toy',agent_backend='mock',allow_experiments=False,tlc_jar=os.environ.get('TLC_JAR'))
    config.budget.agent_calls=20;config.budget.exploration_rounds=5;config.budget.semantic_reviews=6
    config.budget.audit_units=0 if wrong else 1
    config.budget.targeted_reads=6;config.budget.outer_reserve_seconds=1
    root=tmp_path/'inquiry-run'
    impl,_,verifier,knowledge=assemble(config)
    return repo,config,root,(impl,CoverageAgent(responses,wrong,weak),verifier,knowledge)


@pytest.mark.real
def test_breadth_and_post_success_review_drive_actual_new_reading(tmp_path,prepared,tlc):
    repo,config,root,args=setup(tmp_path,prepared,weak=True,tlc=tlc)
    state=Engine(config,root,*args).start(repo)
    assert any(c.id=='delivery_goal' for c in state.claims),state.stop_reason
    assert any('z_delivery.py:141:142' in h['added_material_ids'] for h in state.reading_history)
    first=json.loads(Path(state.discovery_path).read_text())
    assert first['units'] and first['reading_requests']
    assert not any(b['id']=='delivery_binding' for b in first['bindings'])
    assert any(t.trigger=='initial_reading' and t.status=='completed' for t in state.inquiry_tasks)
    assert any(c.action=='model_check' and c.outcome=='holds' for c in state.checks),state.stop_reason
    assert any(r.model_id and any(i.status=='disputed' for i in r.items) for r in state.semantic_reviews)
    assert any('counter-to-result handoff' in t.reason for t in state.inquiry_tasks)
    assert not any(r.kind=='F3' for r in state.revisions)
    assert all(c.assessment.value=='unassessed' for c in state.claims)


def test_semantic_review_corrects_real_material_misreading_before_model(tmp_path,prepared):
    repo,config,root,args=setup(tmp_path,prepared,wrong=True)
    state=Engine(config,root,*args).start(repo)
    claim=next(c for c in state.claims if c.id=='delivery_obligation')
    assert claim.description=='Return in memory mode requires acceptance',state.stop_reason
    assert claim.version==2 and not state.models
    assert state.revisions[0].kind=='F2' and state.revisions[0].before['properties'] is None
    assert any(r.target_versions.get(claim.id)==2 for r in state.semantic_reviews)
    prompts=[p.read_text() for p in (root/'agent').glob('*/prompt.txt')]
    assert any('SEMANTIC REVERSE REVIEW' in p and 'Memory mode promises acceptance on return' in p for p in prompts)


def test_inquiry_without_local_units_keeps_budget_blockage_visible(tmp_path,prepared):
    repo,config,root,args=setup(tmp_path,prepared,wrong=True)
    config.budget.semantic_reviews=0;config.budget.exploration_rounds=1
    state=Engine(config,root,*args).start(repo)
    assert any(t.kind=='review' and t.status=='blocked' for t in state.inquiry_tasks)
    assert 'incomplete' in state.stop_reason
    assert not state.semantic_reviews


def test_outer_action_checkpoint_resume_does_not_repeat_generation(tmp_path,prepared):
    repo,config,root,args=setup(tmp_path,prepared,wrong=True)
    class Interrupted(Engine):
        interrupted=False
        def checkpoint(self,event):
            super().checkpoint(event)
            if not self.interrupted and event=='action_result_saved' and self.state.active_inquiry_id:
                self.interrupted=True
                raise RuntimeError('Interrupt after the actual inquiry result was persisted')
    with pytest.raises(RuntimeError):Interrupted(config,root,*args).start(repo)
    before=Store(root).load()
    active=before.active_inquiry_id
    assert active and before.pending_action.status=='completed'
    cached=json.loads((root/'actions'/before.pending_action.id/'result.json').read_text())[0]['id']
    state=Engine(config,root,*args).resume()
    task=next(t for t in state.inquiry_tasks if t.id==active)
    assert task.status=='completed' and task.check_id==cached
    assert len([c for c in state.checks if c.id==cached])==1
    assert next(c for c in state.claims if c.id=='delivery_obligation').version==2


def test_no_units_still_explores_unrepresented_responsibilities(tmp_path,prepared):
    repo,config,root,args=setup(tmp_path,prepared)
    config.budget.audit_units=0
    class NoInitialGoals(CoverageAgent):
        def analyze(self,*args,**kwargs):
            check,response=super().analyze(*args,**kwargs)
            if type(response).__name__=='Discovery':
                response.claims=[];response.bindings=[];response.relations=[];response.units=[]
                for role in response.responsibilities:role.claim_ids=[]
            return check,response
    impl,agent,verifier,knowledge=args
    agent=NoInitialGoals(prepared[3])
    state=Engine(config,root,impl,agent,verifier,knowledge).start(repo)
    assert any(c.id=='delivery_goal' for c in state.claims),state.stop_reason
    assert any('z_delivery.py:141:142' in h['added_material_ids'] for h in state.reading_history)
    assert not state.models


def test_report_separates_discovery_review_and_local_evidence(tmp_path,prepared):
    repo,config,root,args=setup(tmp_path,prepared,wrong=True)
    state=Engine(config,root,*args).start(repo)
    text=render_report(state,root).read_text()
    assert '不计算全系统覆盖率' in text
    assert '本次范围内暂未发现语义问题' in text
    assert '历史语义版本' in text and '当前对象版本' in text
    assert 'Return in memory mode requires acceptance' in text
    assert '100%' not in text and not state.models
    assert 'blocked' in state.stop_reason
    assert state.units[0].remaining_obligation_ids==['delivery_obligation']
