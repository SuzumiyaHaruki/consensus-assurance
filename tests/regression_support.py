"""Explicit budgets for historical local-chain fixtures, not the default product workflow."""
from consensus_assurance.core.config import Config as ProductConfig


def fixture_config(**kwargs):
    config=ProductConfig(**kwargs)
    config.budget.exploration_rounds=0
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


def descriptive_inventory(material_id):
    from consensus_assurance.core.proposals import Discovery
    from consensus_assurance.core.types import ConsensusAuditSpec,TargetProfile,Activity,Behavior,Fact
    spec=ConsensusAuditSpec(target_profile=TargetProfile(system_boundary='Controlled local fixture',source_ids=[material_id]),
        activities=[Activity(class_id='A'+str(n),applicability='unknown',purpose='Controlled responsibility coordinate',realization_summary='The execution fixture does not claim autonomous coverage',source_ids=[material_id],unknowns=['Actual responsibility requires analysis']) for n in range(1,8)])
    spec.behaviors=[Behavior(id='fixture_step',primary_activity='A1',execution_owner='local loop',protocol_context='local step',trigger='step',produces_fact_ids=['fixture_value'],consumes_fact_ids=['fixture_value'],source_ids=[material_id])]
    spec.facts=[Fact(id='fixture_value',meaning='The local value before and after a step',identity={'instance':'local'},validity_context='local execution',established_by=['fixture_step'],consumed_by=['fixture_step'],representation=['value'],durability='volatile',recovery='not modeled',source_ids=[material_id])]
    return Discovery(understanding='Explicit synthetic inventory for downstream verification regression',audit_spec=spec)


def inventory_response(runner,prompt,directory,snapshot_id,timeout):
    import json
    from consensus_assurance.adapters.agents.backend import MockAgent
    from consensus_assurance.core.proposals import Discovery
    from consensus_assurance.workflow.sources import all_materials
    packet=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])
    source=all_materials(packet)[0]['id']
    agent=MockAgent();agent.responses=[descriptive_inventory(source).model_dump(mode='json')]
    return MockAgent.analyze(agent,runner,prompt,directory,snapshot_id,timeout,Discovery)


def bounded_derivation(graph):
    """Convert a fixed graph fixture into the current bounded backend response."""
    from consensus_assurance.core.proposals import Derivation
    if hasattr(graph,'model_dump'):graph=graph.model_dump(mode='json')
    unit=graph['units'][0];primary=unit['obligation_ids'][0]
    selected=[b for b in graph['bindings'] if b['id'] in unit['binding_ids']]
    edges=[r for r in graph['relations'] if r['id'] in unit['relation_ids']]
    wanted={primary}|{r[k] for r in edges for k in ('source','target')}
    for b in selected:wanted.update(a['claim_id'] for a in b.get('associations',[]) or [{'claim_id':b.get('claim_id')}])
    question=unit.get('audit_question')
    if not question or not question.get('fact_ids'):
        from consensus_assurance.core.types import AuditQuestion
        source=next(c for c in graph['claims'] if c['id']==primary)['source_ids']
        question=AuditQuestion(question='Does the local step respect the declared bound?',importance='Bounded service value',source_ids=source,activity_classes=['A1'],behavior_ids=['fixture_step'],fact_ids=['fixture_value'],obligation_relation_kind='establishment',trigger_rationale='Controlled verification fixture',preferred_check='local_model',disposition='ready_for_check').model_dump(mode='json')
    return Derivation(obligation=next(c for c in graph['claims'] if c['id']==primary),bindings=selected,dependencies=edges,
        context_claims=[c for c in graph['claims'] if c['id'] in wanted and c['id']!=primary],audit_question=question,selection_rationale=unit['rationale']).model_dump(mode='json')


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
