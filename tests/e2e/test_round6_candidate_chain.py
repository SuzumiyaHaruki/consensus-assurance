"""Synthetic multi-object repair goes through the actual review/build/search controller."""
import json
import os
from pathlib import Path
import pytest
from coverage_support import CoverageAgent,add_coverage_materials
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import Discovery
from consensus_assurance.core.types import CodeUse,Origin
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.output_repair import OutputRepair
from consensus_assurance.adapters.storage.files import write_json


@pytest.mark.real
def test_multiple_candidate_repairs_enter_review_and_real_model_check(tmp_path,prepared,tlc):
    repo,_,_,responses=prepared;add_coverage_materials(repo)
    class RepairedAgent(CoverageAgent):
        def analyze(self,runner,prompt,directory,snapshot_id,timeout,response_type):
            if response_type is OutputRepair:
                context=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1]);replacements=[]
                for target in context['repair_targets']:
                    if target['path']=='/bindings/0/symbol':replacements.append({'path':target['path'],'value_json':'"step"'})
                    if target['path']=='/units/0/code_uses':
                        use=CodeUse(binding_id='input_binding',role='input',claim_ids=['input_obligation'],relation_ids=['input_dependency'],source_ids=['limits.py:1:2'],rationale='Actual input dependency is selected; only step responsibility is checked here',unverified=['Upstream guarantee has not been checked'])
                        replacements.append({'path':target['path'],'value_json':json.dumps([use.model_dump(mode='json')])})
                response=OutputRepair(replacements=replacements,rationale='Correct location spelling and declare existing boundary use without changing goals or scope')
                directory.mkdir(parents=True);(directory/'prompt.txt').write_text(prompt);write_json(directory/'response.json',response)
                import sys
                check=runner.run([sys.executable,'-c','print("explicit synthetic repair response")'],directory,'agent',snapshot_id,timeout);check.origin=Origin.MOCK
                return check,response
            check,response=super().analyze(runner,prompt,directory,snapshot_id,timeout,response_type)
            if response_type is Discovery:
                response.bindings[0].symbol='MissingStep'
                edge=next(r for r in responses[1]['relations'] if r['id']=='input_dependency')
                from consensus_assurance.core.proposals import RelationDraft
                response.relations.append(RelationDraft.model_validate(edge));response.units[0].relation_ids.append(edge['id'])
                response.units[0].binding_ids.append('input_binding')
                write_json(directory/'decoded-response.json',response)
                write_json(directory/'response.json',response)
            return check,response
    cfg=Config(implementation='toy',agent_backend='mock',allow_experiments=False,tlc_jar=os.environ['TLC_JAR'])
    cfg.budget.agent_calls=22;cfg.budget.audit_units=1;cfg.budget.semantic_reviews=6;cfg.budget.exploration_rounds=3;cfg.budget.outer_reserve_seconds=1
    root=tmp_path/'run';impl,_,verifier,knowledge=assemble(cfg)
    state=Engine(cfg,root,impl,RepairedAgent(responses),verifier,knowledge,'').start(repo)
    assert state.models,state.stop_reason
    assert any(c.action=='model_check' and c.outcome=='holds' for c in state.checks),state.stop_reason
    assert state.semantic_reviews
    session=next(iter(state.repair_sessions.values()));assert session['status']=='accepted'
    original=json.loads(Path(session['original_path']).read_text());current=json.loads(Path(session['current_path']).read_text())
    assert original['claims']==current['claims']
    assert original['units'][0]['scope']==current['units'][0]['scope']
    assert original['units'][0]['obligation_ids']==current['units'][0]['obligation_ids']
    assert any(t.trigger.startswith('after_local:') for t in state.inquiry_tasks)


@pytest.mark.real
def test_explicit_encoding_repair_runs_again_and_keeps_correspondence_issue(tmp_path,prepared,tlc):
    from consensus_assurance.core.proposals import BuildReply
    from consensus_assurance.adapters.agents.backend import MockAgent
    from regression_support import fixture_config
    repo,_,bundle,responses=prepared
    broken=bundle.model_copy(deep=True);broken.properties=broken.properties.replace('value <= 3','value <= )')
    fixed=BuildReply(bundle=bundle,gap='',encoding_revision={'old_model_id':'CURRENT','source_ids':['README.md:1:5'],'rationale':'Correct the malformed comparison token for the unchanged bound'})
    fixture=tmp_path/'encoding.json';write_json(fixture,[responses[0],responses[1],BuildReply(bundle=broken,gap='').model_dump(mode='json'),fixed.model_dump(mode='json')])
    class EncodingAgent(MockAgent):
        def analyze(self,runner,prompt,directory,snapshot_id,timeout,response_type):
            check,response=super().analyze(runner,prompt,directory,snapshot_id,timeout,response_type)
            if isinstance(response,BuildReply) and response.encoding_revision:
                context=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1]);response.encoding_revision.old_model_id=context['model_id']
                write_json(directory/'decoded-response.json',response)
                write_json(directory/'response.json',response)
            return check,response
    cfg=fixture_config(implementation='toy',agent_backend='mock',fixture=str(fixture),allow_experiments=False,tlc_jar=os.environ['TLC_JAR'])
    cfg.budget.audit_units=1
    impl,_,verifier,knowledge=assemble(cfg)
    state=Engine(cfg,tmp_path/'encoding-run',impl,EncodingAgent(fixture),verifier,knowledge,'').start(repo)
    assert len(state.models)==2,state.stop_reason
    assert any(c.action=='model_check' and c.reason=='Model syntax error' for c in state.checks)
    assert any(c.action=='model_check' and c.outcome=='holds' for c in state.checks)
    assert any(i.needs_recheck and i.resolved_by is None for i in state.review_issues)
    assert '<= )' in Path(state.models[0].path).read_text()
    assert [c.description for c in state.claims]==[c['description'] for c in responses[1]['claims']]
