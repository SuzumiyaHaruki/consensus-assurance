"""Synthetic saved records for validation and projections, without running an Agent or target."""
import json

from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import (
    Analysis, CheckRun, ExperimentBasis, FixedExperiment, Harness, Interpretation,
    Investigation, Material, Snapshot,
)
from consensus_assurance.workflow.engine import FRAMEWORK_REVISION
from consensus_assurance.workflow.experiments import fixed_files, measurement_inputs, observed
from support.audit import experiment, first, opinion


def research_state(root):
    submission, _ = first({})
    question = submission['investigations'][0].copy()
    question.pop('ref')
    return Analysis(
        mode='mock', framework_revision=FRAMEWORK_REVISION,
        config=Config(agent_backend='mock', execution_backend='python').model_dump(mode='json'),
        snapshot=Snapshot(id='snapshot', repo=str(root / 'source'),
                          files={'target.py': 'fixture', 'README.md': 'fixture'}, excluded=[]),
        materials=[Material(**source, text='Synthetic source excerpt', content_digest='fixture')
                   for source in submission['sources']],
        investigations=[Investigation(id='question', operation_id='start', **question)],
    )


def saved_evidence(root, *, events=None, basis_changes=None, name='sample'):
    state = research_state(root)
    state.investigations[0].id = name + '-question'
    request, files = experiment(state.investigations[0].id)
    request.pop('investigation_id')
    request.pop('harness_path')
    requirements = request.pop('prerequisites')
    basis = ExperimentBasis(harness=Harness(kind='python', source=files['check.py'],
                                           prerequisites=requirements), **request)
    for key, value in (basis_changes or {}).items():
        setattr(basis, key, value)
    fixed = FixedExperiment(id=name + '-fixed', investigation_id=state.investigations[0].id, basis=basis,
        snapshot_id=state.snapshot.id, configuration={}, harness_filename='check.py', operation_id='start')
    folder = root / 'logs' / (name + '-receipt')
    folder.mkdir(parents=True)
    if events is None:
        events = [dict(event='admitted', operation='one', value=3, limit=3),
                  dict(event='returned', operation='one', value=0)]
    (folder / 'stdout.log').write_text(''.join(
        'CA_EVENT ' + (event if isinstance(event, str) else json.dumps(event)) + '\n' for event in events))
    (folder / 'stderr.log').write_text('')
    check = CheckRun(id=name + '-receipt', action='experiment', experiment_id=fixed.id, cwd=str(root),
        snapshot_id=state.snapshot.id, origin='synthetic_trace', status='completed', exit_code=0,
        started_at='2026-01-01T00:00:00+00:00', ended_at='2026-01-01T00:00:01+00:00',
        stdout=str(folder / 'stdout.log'), stderr=str(folder / 'stderr.log'),
        parameters={'changed_target_files': []})
    state.experiments.append(fixed)
    state.checks.append(check)
    state.current_submission = dict(phase='executed', operation_id='start', experiment_id=fixed.id)
    fixed_files(root, fixed, write=True)
    write_json(folder / 'check.json', check)
    write_json(folder / 'observations.json', {
        **observed(fixed, check, root), '_inputs': measurement_inputs(fixed, check, root)})
    return state, fixed, check


def append_interpretation(state, **changes):
    submission, _ = opinion(state.model_dump(mode='json'), **changes)
    operation = f'account-{len(state.interpretations)}'
    value = Interpretation(id=operation, operation_id=operation, **submission['interpretations'][0])
    state.interpretations.append(value)
    state.current_submission = dict(phase='accepted', operation_id=operation)
    return value
