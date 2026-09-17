"""Reproduce archived failures through current project types, without external calls."""
import json
import shutil
from pathlib import Path
import pytest
from consensus_assurance.core.types import Analysis
from consensus_assurance.core.proposals import ReviewReply, GraphPatch
from consensus_assurance.workflow.reviews import validate_resolutions
from consensus_assurance.workflow.scope_updates import from_patch,validate_scope_update
from consensus_assurance.workflow.output_repair import diagnostic_targets
from test_round6_boundaries import controller

ARCHIVE=Path(__file__).resolve().parents[1]/'fixtures/recorded_repair'

def archived():return Analysis.model_validate_json((ARCHIVE/'state.json').read_text())
def reply(folder):return json.loads((ARCHIVE/'agent'/folder/'decoded-response.json').read_text())

def test_archived_resolution_does_not_require_all_old_citations():
    s=archived();r=ReviewReply.model_validate(reply('8a7fe58d21194075bf8d501221a837f8-semantic_review'))
    prompt=(ARCHIVE/'agent/8a7fe58d21194075bf8d501221a837f8-semantic_review/prompt.txt').read_text()
    packet=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])
    from consensus_assurance.core.types import InquiryTask
    t=InquiryTask.model_validate(packet['task'])
    from consensus_assurance.workflow.output_repair import all_materials
    t.material_ids=[m['id'] for m in all_materials(packet)]
    before=s.model_dump()
    with pytest.raises(ValueError) as caught:validate_resolutions(s,t,r)
    assert caught.value.diagnostics[0].code=='condition_missing'
    # Offline supplement only: preserve all original opinions and classify residual scope.
    from consensus_assurance.core.proposals import ConditionDisposition
    for resolution in r.resolutions:
        item=next(i for i in r.items if i.target_id=='R_apply_commit' and i.aspect=='decomposition')
        resolution.condition_dispositions=[ConditionDisposition(condition=x,applies_to='independent_scope',source_ids=resolution.source_ids,
            rationale='The issue asks to locate the leader dispatch handoff; complete future/batch semantics and acceptance of a separate grounding revision remain open beyond that handoff') for x in item.limitations]
    validate_resolutions(s,t,r)
    from consensus_assurance.workflow.inquiry import validate_review
    from consensus_assurance.workflow.history import import_question_changes
    validate_review(s,t,import_question_changes(r))
    assert s.model_dump()==before


def test_cached_plans_leave_new_source_quota(tmp_path,prepared):
    repo,s,_,_=prepared;e=controller(tmp_path,s);shutil.copytree(repo,e.root/'source')
    e.config.budget.targeted_reads=2;s.usage['targeted_reads']=2
    q=[dict(file='limits.py',start_line=1,end_line=2,reason='Reattach actual cached source')]
    for i in range(4):assert e.read(q,plan_id='cache-'+str(i))['status']=='complete'
    assert s.usage['targeted_reads']==2


def test_scope_diagnostics_resolve_original_candidate_ids():
    s=archived();p=GraphPatch.model_validate(reply('f6577be6da9a47f68581404d750a55d6-graph_patch'))
    u=next(u for u in s.units if u.id=='U_commit');update=from_patch(s,u,p)
    with pytest.raises(ValueError) as exc:validate_scope_update(s,update)
    ds=exc.value.diagnostics
    uses=[d for d in ds if d.code=='unit_code_use']
    # Location failures remain independent; temporary IDs never leak as repair identities.
    assert all(not any('.scope.' in id for id in d.object_ids) for d in ds)
    targets=diagnostic_targets(p.model_dump(mode='json'),ds,100000)
    assert any(t['path'].startswith('/bindings/') for t in targets)
    if uses:assert any(t['path']=='/units/0/code_uses' for t in targets)
