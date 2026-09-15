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
