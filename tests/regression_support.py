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
