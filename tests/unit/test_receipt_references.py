"""Reference diagnostics without rerunning an experiment for each malformed submission."""
from copy import deepcopy
import pytest
from support.audit import opinion
from support.evidence import saved_evidence, append_interpretation
from consensus_assurance.adapters.runners.python import PythonBackend
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.workflow.audit import validate_submission


@pytest.fixture
def evidence(tmp_path):
    state, fixed, check = saved_evidence(tmp_path)
    append_interpretation(state)
    state.checks.append(check.model_copy(update={'id': 'turn', 'action': 'agent_turn', 'experiment_id': None}))
    return state, fixed, check


def product(state):
    sub, _ = opinion(state.model_dump(mode='json'))
    sub['knowledge'] = [dict(kind='fact', statement='The selected call returned zero.',
        conditions='The recorded admitted operation', source_ids=['code'],
        executions=deepcopy(sub['interpretations'][0]['executions']))]
    return sub


def preflight(root, state, submission):
    write_json(root / 'draft' / 'references.json', submission)
    before = state.model_dump(mode='json')
    saved = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = validate_submission(state, root, 'references.json', PythonBackend())
    assert state.model_dump(mode='json') == before
    assert {p: p.read_bytes() for p in root.rglob('*') if p.is_file()} == saved
    return result


@pytest.mark.parametrize('collection', ['knowledge', 'interpretations'])
@pytest.mark.parametrize('kind', ['not_found', 'CheckRun', 'Interpretation', 'FixedExperiment'])
def test_all_reference_identities_are_checked_before_measurement(tmp_path, monkeypatch, evidence, collection, kind):
    state, fixed, check = evidence
    sub = product(state)
    sub[collection].append(deepcopy(sub[collection][0]))
    id = {'not_found': 'missing', 'CheckRun': 'turn', 'Interpretation': state.interpretations[0].id,
          'FixedExperiment': fixed.id}[kind]
    sub[collection][-1]['executions'] = {id: [1]}
    monkeypatch.setattr('consensus_assurance.workflow.experiments.observed',
        lambda *a, **kw: pytest.fail('Identity errors must precede all measurement reads'))
    diagnostic, = preflight(tmp_path, state, sub)['diagnostics']
    assert diagnostic['code'] == 'execution_reference' and diagnostic['category'] == 'association'
    assert diagnostic['paths'] == [f'/{collection}/1/executions/{id}']
    assert diagnostic['object_ids'] == [id] and diagnostic['details']['actual_kind'] == kind
    assert diagnostic['details']['execution_index'] == {'path': 'state.json', 'collection': 'checks'}
    assert 'observations' not in diagnostic['details']


def test_snapshot_identity_precedes_measurement(tmp_path, monkeypatch, evidence):
    state, fixed, check = evidence
    check.snapshot_id = 'another-snapshot'
    monkeypatch.setattr('consensus_assurance.workflow.experiments.observed',
        lambda *a, **kw: pytest.fail('Snapshot mismatch must precede measurement'))
    diagnostic, = preflight(tmp_path, state, product(state))['diagnostics']
    assert diagnostic['code'] == 'execution_reference'
    assert diagnostic['details']['snapshot_id'] == 'another-snapshot'
    assert diagnostic['details']['expected_snapshot_id'] == state.snapshot.id


def test_alias_and_joint_history_do_not_change_experiment_ownership(tmp_path, evidence):
    state, fixed, check = evidence
    sub = product(state)
    sub['investigations'] = [dict(ref='@related', question='Can this observation inform a related question?', source_ids=['code'])]
    sub['interpretations'].append({**sub['interpretations'][0], 'investigation_id': '@related',
        'experiment_id': None, 'conclusion': 'explained', 'defect_claim': 'asserted'})
    diagnostic, = preflight(tmp_path, state, sub)['diagnostics']
    assert diagnostic['code'] == 'execution_reference'
    assert diagnostic['paths'] == [f'/interpretations/1/executions/{check.id}']
    assert 'joint-history' in diagnostic['message']
    sub['interpretations'][1]['joint_history'] = 'Reuse the same recorded local operation, not a new execution.'
    assert preflight(tmp_path, state, sub)['valid']
    sub['interpretations'][1]['experiment_id'] = fixed.id
    diagnostic, = preflight(tmp_path, state, sub)['diagnostics']
    assert diagnostic['code'] == 'interpretation_experiment' and diagnostic['category'] == 'association'
    assert diagnostic['paths'] == ['/interpretations/1/investigation_id', '/interpretations/1/experiment_id']
    assert diagnostic['object_ids'] == ['preflight-question-0', fixed.id, fixed.investigation_id]
    assert diagnostic['details'] == {
        'submitted_investigation_id': '@related', 'investigation_id': 'preflight-question-0',
        'experiment_id': fixed.id, 'experiment_investigation_id': fixed.investigation_id, 'conclusion': 'explained',
        'experiment_record': {'path': 'state.json', 'collection': 'experiments', 'id': fixed.id},
        'owner_record': {'path': 'state.json', 'collection': 'investigations', 'id': fixed.investigation_id},
        'navigation': 'research.json'}
    assert 'omit experiment_id' in diagnostic['message']
    assert 'joint_history does not change experiment ownership' in diagnostic['message']
    bound = deepcopy(sub)
    bound['interpretations'][1]['investigation_id'] = fixed.investigation_id
    assert preflight(tmp_path, state, bound)['valid']
    sub['interpretations'][1]['experiment_id'] = None
    for conclusion in ('explained', 'conditional', 'unresolved', 'violated', 'holds'):
        sub['interpretations'][1]['conclusion'] = conclusion
        result = preflight(tmp_path, state, sub)
        assert result['valid'] == (conclusion in {'explained', 'conditional', 'unresolved'})
        if not result['valid']:
            assert 'Measured conclusions require a fixed experiment' in result['diagnostics'][0]['message']


@pytest.mark.parametrize('collection', ['knowledge', 'interpretations'])
def test_event_reference_diagnostic_locates_invalid_and_duplicate_indices(tmp_path, evidence, collection):
    state, fixed, check = evidence
    sub = product(state)
    sub[collection][0]['executions'] = {check.id: [-1, 1, 1, 2]}
    diagnostic, = preflight(tmp_path, state, sub)['diagnostics']
    assert diagnostic['code'] == 'event_indices' and diagnostic['category'] == 'association'
    assert diagnostic['paths'] == [f'/{collection}/0/executions/{check.id}']
    assert diagnostic['object_ids'] == [check.id]
    assert diagnostic['details'] == dict(invalid_indices=[-1, 2], duplicate_indices=[1], event_count=2,
        valid_range=[0, 1], observations=f'logs/{check.id}/observations.json', stdout=check.stdout)
    assert 'Fix the citation array' in diagnostic['message'] and '0 through 1' in diagnostic['message']
