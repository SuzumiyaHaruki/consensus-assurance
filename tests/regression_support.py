"""Explicit budgets for historical local-chain fixtures, not the default product workflow."""
from consensus_assurance.core.config import Config as ProductConfig


def fixture_config(**kwargs):
    config=ProductConfig(**kwargs)
    config.budget.semantic_reviews=0
    return config


def declared_changes(state, feedback):
    """Construct explicit changes in controlled fixtures; production never fills missing declarations."""
    import json
    from consensus_assurance.workflow.mutations import write_set
    from consensus_assurance.core.proposals import JudgmentChange
    feedback.changes=[JudgmentChange(target_id=id,field=field,old_value_json=json.dumps(before),new_value_json=json.dumps(after)) for (id,field),(before,after) in write_set(state,feedback.patch).items()]
    return feedback


def toy_responses(repo):
    """Instantiate the synthetic whole-document citation against the copied fixture.

    Fixed code intervals remain intentional test inputs. This does not migrate
    archived runs or normalize real backend responses.
    """
    import json
    from pathlib import Path
    responses=json.loads((Path(__file__).parent/'fixtures/toy_responses.json').read_text())
    request=next(r for r in responses[0]['requests'] if r['file']=='README.md')
    old_id=f"README.md:{request['start_line']}:{request['end_line']}"
    request['end_line']=len((Path(repo)/'README.md').read_text().splitlines())
    new_id=f"README.md:1:{request['end_line']}"
    def replace(value):
        if isinstance(value,str):return new_id if value==old_id else value
        if isinstance(value,list):return [replace(v) for v in value]
        if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
        return value
    return replace(responses)


def add_dependency(state,responses):
    from consensus_assurance.core.types import Relation
    edge=Relation(id='input_dependency',source='step_obligation',target='input_obligation',kind='boundary',group=None,
        rationale='The checked consumer depends on actual producer input',pending=['Producer guarantee remains unverified'],grounding=state.claims[1].grounding.model_copy(deep=True))
    if not state.relations:state.relations.append(edge)
    from consensus_assurance.core.proposals import RelationDraft
    responses[1]['relations']=[{k:v for k,v in edge.model_dump(mode='json').items() if k in RelationDraft.model_fields}]
    state.units[0].relation_ids=['input_dependency'];responses[1]['units'][0]['relation_ids']=['input_dependency']


def fixture_reachability(bundle):
    """Explicit toy step trigger for the structured establishment question."""
    import copy
    result=copy.deepcopy(bundle)
    if result.get('reachability'):return result
    result['behavior']=result['behavior'].replace('vars ==', 'FixtureStep == value = 1\nvars ==',1)
    result['reachability']=[{'id':'fixture_step_reached','operator':'FixtureStep','claim_ids':['step_obligation'],
        'behavior_ids':['fixture_step'],'fact_ids':['fixture_value'],'description':'The isolated toy step establishes value one'}]
    return result


def read_material(repo, snapshot, request):
    from consensus_assurance.core.types import Material
    path=repo/request.file
    text="\n".join(path.read_text().splitlines()[request.start_line-1:request.end_line])
    return Material(id=f"{request.file}:{request.start_line}:{request.end_line}",file=request.file,
        start_line=request.start_line,end_line=request.end_line,text=text,
        kind='document_statement' if path.suffix=='.md' else 'code_observation',
        content_digest=snapshot.files[request.file])


def add_reads(state,repo,reading,budget):
    additions=[read_material(repo,state.snapshot,r) for r in reading.requests]
    known={m.id for m in state.materials}
    state.materials.extend(m for m in additions if m.id not in known)
    return [m.id for m in additions]


from consensus_assurance.core.proposals import ReadRequest
from consensus_assurance.core.types import Record

class ReadingPlan(Record):
    requests: list[ReadRequest]
    rationale: str = ""
    gap: str = ""
    related_ids: list[str] = []
