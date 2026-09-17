from consensus_assurance.workflow.history import import_record
"""Offline method routing and handoff representation, not agent-quality evidence."""
import json
from pathlib import Path

import pytest

from consensus_assurance.core.types import Analysis, AuditQuestion, AuditUnit, Binding, Claim, Relation
from consensus_assurance.workflow.discovery import context
from consensus_assurance.workflow.prompts import loaded_resources, render
from test_worksets import ARCHIVE, archived_engine

RESOURCES = Path(__file__).resolve().parents[2] / 'src/consensus_assurance/resources'
SURVEY = 'skills/consensus-analysis/references/activity-classes.md'
BEHAVIOR = 'skills/consensus-analysis/references/behavior-facts.md'
GUIDE = 'skills/consensus-analysis/guide.md'


@pytest.mark.parametrize('task', ['read', 'discover', 'spec_refine', 'build', 'F1', 'F3', 'technical'])
def test_controller_renders_selected_reference_bodies(task):
    paths = loaded_resources(task, {})['paths']
    expected = [SURVEY] if task == 'read' else [SURVEY, BEHAVIOR] if task in {'discover', 'spec_refine'} else [BEHAVIOR]
    prompt = render(task, {})
    for path in expected:
        assert path in paths
        assert (RESOURCES / path).read_text() in prompt
    if task == 'read':
        assert GUIDE not in paths and BEHAVIOR not in paths
    retry = render('retry', {'original_task': task})
    for path in loaded_resources('retry',{'original_task':task})['paths']:
        assert (RESOURCES / path).read_text() in retry


def test_default_methods_are_target_independent_and_review_stays_compact():
    methods = '\n'.join(p.read_text() for p in (RESOURCES / 'skills/consensus-analysis').rglob('*.md'))
    assert 'CFT' in methods
    for target_answer in ['HashiCorp', 'etcd', 'O_commit', 'O_append_evidence', 'O_fsm_handoff', 'processLogs']:
        assert target_answer not in methods
    for obsolete in ['Membership/weight', 'QC', 'threshold signature', 'global maximum', 'certificate']:
        assert obsolete not in methods
    paths = loaded_resources('semantic_review', {})['paths']
    assert BEHAVIOR not in paths and SURVEY not in paths and GUIDE not in paths


# These are authored alternative contracts, not expected model answers. The test
# verifies that the same existing workset route carries each variant unchanged.
@pytest.mark.parametrize('variant,path,protection,check', [
    ('pre-election enabled', 'probe -> formal campaign', 'probe does not persist a formal vote', 'code review: inspect transition to formal campaign'),
    ('no pre-election', 'timeout -> formal campaign', 'formal campaign owns vote persistence', 'direct test: observe durable vote before affirmative response'),
    ('contact maintenance enabled', 'contact timer -> authority change request', 'new work checks authority', 'controlled schedule: delay acknowledgement of the change request'),
    ('no contact maintenance', 'replication -> supported decision', 'decision requires applicable replication support', 'code review: trace support consumed by a decision'),
    ('transfer bypass', 'transfer request -> bypass probe -> formal campaign', 'formal vote validation remains', 'direct test: compare normal and bypass vote effects'),
    ('serialized event loop', 'handler -> owned state -> response', 'one loop owns state during handler', 'code review: locate all writers and blocking boundaries'),
    ('async callback', 'request -> callback after object replacement', 'callback retains original object', 'controlled schedule: complete old callback after replacement'),
    ('external persistence adapter', 'capture -> adapter.persist -> publish -> restore', 'publication waits for adapter completion', 'direct test: adapter failure before publication; observe recovery consumer'),
])
def test_conditional_variants_survive_existing_workset(tmp_path, prepared, variant, path, protection, check):
    from test_graph_mutations import controller
    _, state, _, _ = prepared
    unit = state.units[0]
    question = unit.audit_question.model_copy(deep=True) if unit.audit_question else AuditQuestion(
        question='Which event establishes the fact consumed by this path?', importance='Preserve the applicable service guarantee',
        source_ids=state.claims[0].source_ids, trigger_rationale=check)
    question.contexts = [variant]
    question.event_paths = [path, 'Known protection: ' + protection]
    question.trigger_rationale = check
    unit.audit_question = question
    before = unit.model_dump_json()
    packet = context(controller(tmp_path, state), unit)
    assert packet['unit']['audit_question'] == question.model_dump(mode='json')
    assert unit.model_dump_json() == before
    prompt = render('build', packet)
    for value in (variant, path, protection, check):
        assert value in prompt


def latest_engine():
    e = archived_engine('b69d50c2a0ac4e20897e36c355f034ef')
    e.state = Analysis.model_validate(__import__("consensus_assurance.workflow.history",fromlist=["import_record"]).import_record(json.loads((ARCHIVE / 'state.json').read_text())))
    return e


@pytest.mark.parametrize('unit_id,next_check', [
    ('U_commit', 'explained_by_existing_mechanism: local sorting, majority selection and monotonic guards explain local arithmetic. Preferred next check: code review of report provenance; delivery remains separate.'),
    ('U_snapshot', 'needs_specific_evidence: separate capture, Persist/Close, publication, compaction and recovery consumer. Preferred next check: direct test of one configured sink failure before publication; other stores deferred.'),
])
def test_archived_units_can_carry_bounded_next_check_without_erasing_conditions(unit_id, next_check):
    e = latest_engine()
    unit = next(u for u in e.state.units if u.id == unit_id)
    original = unit.model_dump(mode='json')
    # Offline analyst continuation only; the retained archive is never rewritten.
    unit.audit_question.trigger_rationale += '\n' + next_check
    packet = context(e, unit)
    assert next_check in packet['unit']['audit_question']['trigger_rationale']
    assert packet['unit']['scope'] == original['scope']
    assert packet['unit']['coverage_limitations'] == original['coverage_limitations']
    assert packet['unit']['audit_question']['event_paths'] == original['audit_question']['event_paths']
    assert set(unit.obligation_ids) <= {c['id'] for c in packet['claims']}
    assert unit.binding_ids and packet['bindings'] and packet['materials']
    assert set(unit.audit_question.source_ids) <= set(packet['required_material_ids'])
    assert 'semantic_reviews' not in packet


def test_replication_original_request_discriminator_does_not_erase_other_gaps():
    e = latest_engine()
    claim = next(c for c in e.state.claims if c.id == 'O_append_evidence')
    original = claim.model_dump(mode='json')
    source = (ARCHIVE / 'source/replication.go').read_text().splitlines()
    helper = '\n'.join(source[654:665])
    assert 'req.Entries' in helper and 's.commitment.match(s.peer.ID, last.Index)' in helper
    assert 'updateLastAppended(s, &req)' in '\n'.join(source[240:254])
    question = AuditQuestion(
        question='What stored prefix does success confirm, including stale, duplicate, partial, error and alternate paths?',
        importance='Progress accounting consumes report provenance, not only quorum arithmetic.',
        source_ids=['replication.go:655:665', 'replication.go:202:298'],
        contexts=['Successful non-pipelined request with entries'],
        event_paths=['Known protection: updateLastAppended uses original request entries, not a later local frontier. Empty requests do not enter the matching update branch.'],
        trigger_rationale='explained_by_existing_mechanism for the later-frontier suspicion only. Preferred next check: code review of follower persistence-before-success and request/peer lifetime; pipeline and snapshot paths remain separate.')
    # A source-file observation is not silently promoted to an acquired runtime
    # material or a resolved review issue. This preview explicitly labels it.
    preview = render('build', {'offline_question_preview': question.model_dump(mode='json'),
        'unacquired_source_excerpt': {'file': 'replication.go', 'start_line': 655, 'end_line': 665, 'text': helper},
        'claim': original})
    assert question.trigger_rationale in preview
    assert claim.model_dump(mode='json') == original
    for unresolved in claim.grounding.unresolved:
        assert unresolved in preview


def test_unaccepted_fsm_candidate_has_compact_behavior_handoff_preview():
    e = latest_engine()
    response = json.loads((ARCHIVE / 'agent/5fb1d7bd68bc4097b644cbaa916722e3-explore/decoded-response.json').read_text())
    patch = response['patch']
    materials = {m.id: m for m in e.state.materials}
    # Inspect representation on a private state; do not apply, accept or repair
    # this historical proposal and do not reinterpret its original failure.
    for c in patch['claims']:
        e.state.claims.append(Claim(**c, source='Offline unaccepted candidate preview'))
    for b in patch['bindings']:
        m = materials[b['material_id']]
        e.state.bindings.append(Binding(**b, file=m.file, snapshot_id=e.state.snapshot.id,
            content_digest=m.content_digest, basis='agent_inference', excerpt='\n'.join(m.text.splitlines()[b['start_line']-m.start_line:b['end_line']-m.start_line+1])))
    e.state.relations.extend(Relation(**r) for r in patch['relations'])
    unit = AuditUnit(**import_record(patch['units'][0]))
    e.state.units.append(unit)
    question = unit.audit_question
    original_unknowns = question.unknowns[:]
    question.event_paths.append('Known protection: batch response selection reuses the input filter and assigns the response to the tuple future after callback return (fsm.go:145:186).')
    question.trigger_rationale = 'ready_for_check: direct test with mixed command/barrier tuples and distinct callback responses; block callback return, observe no early completion, then correlate each response with its original Future. No execution result is claimed.'
    packet = context(e, unit)
    assert packet['unit']['audit_question']['unknowns'] == original_unknowns
    assert set(question.source_ids) <= set(packet['required_material_ids'])
    assert 'processLogs' in json.dumps(packet['unit']['audit_question']['event_paths'])
    assert question.trigger_rationale in render('build', packet)
    assert packet['unit']['scope']['excluded'] == patch['units'][0]['scope']['excluded']
    assert {c['id'] for c in packet['claims']} >= {'O_fsm_handoff', 'G_apply'}
    assert len(packet['bindings']) >= len(patch['bindings'])
