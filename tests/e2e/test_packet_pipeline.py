"""Packet-informed synthetic planning, actual repairs, durable models and real TLC."""
import json
import sys
from pathlib import Path
import pytest
from coverage_support import CoverageAgent
from test_inquiry_loop import setup
from consensus_assurance.core.types import Origin
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.workflow.engine import Engine


class PacketAgent(CoverageAgent):
    def __init__(self,responses,negative=False):
        super().__init__(responses);self.review_fault=False;self.read_fault=False;self.negative=negative
    def analyze(self,runner,prompt,directory,snapshot_id,timeout,response_type):
        packet=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1]);name=response_type.__name__
        if name=='OutputRepair':
            d=packet['active_diagnostics'][0]
            if d['code']=='read_range':
                response={'replacements':[{'path':next(t['path'] for t in packet['repair_targets'] if t['path'].endswith('/end_line')),'value_json':str(d['details']['file_metadata']['lines'])}],
                    'rationale':'Use actual EOF for the same requested file and dependency'}
            else:raise AssertionError(d)
        elif name=='ReviewReply':
            # The responder knows only the public packet contract, not private validator mappings.
            items=[]
            for c in packet['review_contract']:
                for aspect in c['required_aspects']:
                    fault=c['object_type']=='unit' and not self.review_fault
                    if fault:self.review_fault=True
                    items.append({'target_id':c['target_id'],'aspect':'applicability' if fault else aspect,'status':'disputed' if fault else 'no_issue_found','source_ids':c['required_material_ids'],'limitations':[],'rationale':'An unresolved mapping caveat' if fault else 'The bounded synthetic responsibility has supporting source context' + "\n" + 'A correct alternative mechanism may provide the responsibility' + "\n" + 'The code must retain its actual dependency guards'})
            response={'items':items,'limitations':[]}
        elif name=='BuildReply' and not self.read_fault:
            self.read_fault=True
            meta=next((m for m in packet['file_lookup'] if m['file']=='limits.py'),None)
            assert meta or packet['lookup_request']
            # Deliberately invalid synthetic request: an unlisted path must get actual EOF diagnostics too.
            invalid_end=meta['lines']+1 if meta else 1000000
            response={'bundle':None,'gap':'Read the complete actual input normalization dependency',
                'requests':[{'file':'limits.py','start_line':1,'end_line':invalid_end,'reason':'Inspect the dependency before modeling'}]}
        elif name=='BuildReply':
            response={'bundle':json.loads(json.dumps(self.source_responses[2])),'gap':''}
            if self.negative:response['bundle']['properties']=response['bundle']['properties'].replace('value <= 3','value <= 2')
        else:return super().analyze(runner,prompt,directory,snapshot_id,timeout,response_type)
        directory.mkdir(parents=True,exist_ok=True);(directory/'prompt.txt').write_text(prompt)
        write_json(directory/'response.json',response);write_json(directory/'decoded-response.json',response)
        check=runner.run([sys.executable,'-c','print("Explicit packet-informed synthetic responder")'],directory,'agent',snapshot_id,timeout);check.origin=Origin.MOCK
        return check,response_type.model_validate(response)


@pytest.mark.real
@pytest.mark.parametrize('negative',[False,True])
def test_accepted_graph_review_and_read_repairs_reach_real_tlc(tmp_path,prepared,tlc,negative):
    repo,config,root,args=setup(tmp_path,prepared,tlc=tlc)
    config.budget.agent_calls=20;config.budget.material_chars=5000;config.budget.material_chunks=12
    impl,_,verifier,knowledge=args
    agent=PacketAgent(prepared[3],negative)
    state=Engine(config,root,impl,agent,verifier,knowledge).start(repo)
    assert state.models,state.stop_reason
    assert any(c.action=='model_check' and c.outcome==('counterexample' if negative else 'holds') for c in state.checks),state.stop_reason
    assert {'delivery_goal','capacity_goal'}<={c.id for c in state.claims}
    assert any(t.kind=='spec_refine' for t in state.inquiry_tasks)
    sessions=list(state.repair_sessions.values())
    assert {s['task'] for s in sessions}=={'build'}
    assert any(t.trigger.endswith(':missing_aspects') for t in state.inquiry_tasks)
    assert all(s['status']=='accepted' for s in sessions)
    assert any(i.status=='disputed' for r in state.semantic_reviews for i in r.items)
    assert state.usage['agent_calls']<=20
    assert all(Path(m.path).is_file() and Path(m.bundle_path).is_file() for m in state.models)
    assert all(e.origin==Origin.MOCK for e in state.evidence)
    assert not any(f.stage.value=='implementation_reproduced' for f in state.findings)
    assert any(p['duplicate_material_occurrences']==0 for p in state.packet_receipts)
    assert not any(c.action in {'experiment','replay'} for c in state.checks)
