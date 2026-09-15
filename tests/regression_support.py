"""Explicit budgets for historical local-chain fixtures, not the default product workflow."""
from consensus_assurance.core.config import Config as ProductConfig


def fixture_config(**kwargs):
    config=ProductConfig(**kwargs)
    config.budget.exploration_rounds=0
    config.budget.semantic_reviews=0
    return config
