import pytest
from consensus_assurance.core.proposals import GraphDraft
from consensus_assurance.workflow.graph import apply_graph


def test_fake_binding_and_normative_inference_rejected(dependency_prepared):
    _, state, responses  = dependency_prepared
    graph = GraphDraft.model_validate(responses['graph'])
    graph.bindings[0].symbol = "nonexistent_symbol"
    with pytest.raises(ValueError): apply_graph(state, graph)
    graph = GraphDraft.model_validate(responses['graph'])
    graph.claims[0].grounding.derivation = ""
    with pytest.raises(ValueError): apply_graph(state, graph)


from consensus_assurance.core.types import Grounding


def test_code_derived_responsibilities_are_candidates(prepared):
    _, state, responses = prepared
    graph=GraphDraft.model_validate(responses['graph'])
    c=graph.claims[1]
    c.source_ids=['counter.py:1:10','limits.py:1:2']
    c.grounding=Grounding(source_ids=c.source_ids,binding_ids=['step_binding','input_binding'],
        derivation='The consumer assumes a positive limit and the producer must establish that precondition',
        applicability='Serial calls in the fixture',unresolved=['No direct documented contract; inferred responsibility'])
    apply_graph(state,graph)
    assert state.claims[1].candidate
    assert state.claims[1].grounding.unresolved
    c.grounding.binding_ids=['step_binding']
    apply_graph(state,graph)
    assert state.claims[1].candidate
    c.grounding.binding_ids=[]
    with pytest.raises(ValueError,match='located implementation binding'): apply_graph(state,graph)
