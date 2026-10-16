"""End-to-end checks for saved measurements and portable reports."""
import json
import shutil
from support.audit import engine_for, combined, opinion, stop
from consensus_assurance.workflow.experiments import assessment
from consensus_assurance.reporting.report import render_report


def test_measurement_reused_across_current_views_and_readonly_validation(tmp_path, monkeypatch):
    import subprocess
    import sys
    from consensus_assurance.workflow import experiments
    from consensus_assurance.workflow.knowledge import target_receipts
    from consensus_assurance.workflow.research import current_view
    parsed, retained = [], {}
    extract = experiments.extract_events
    def counted(check):
        parsed.append(check.id)
        return extract(check)
    monkeypatch.setattr(experiments, 'extract_events', counted)
    def start(state):
        value, files = combined(state)
        value['gaps'] = [dict(investigation_id='@q', question='Which caller duty applies?')]
        return value, files
    def revise(state):
        fixed = e.state.experiments[0]
        check = next(c for c in e.state.checks if c.experiment_id)
        retained['before'] = assessment(e.state, e.root, fixed, check)
        retained['bytes'] = (e.root/'logs'/check.id/'observations.json').read_bytes()
        return opinion(state, experiment_id=None, executions={}, conclusion='conditional', defect_claim='unresolved',
            rationale='Source research narrows the duty; withdraw the earlier execution-based claim.',
            answers={state['investigations'][0]['gaps'][0]['id']:
                dict(resolved=True, explanation='The defining source supplies the caller duty.')})
    e, repo = engine_for(tmp_path, [start, opinion, revise, stop])
    state = e.start(repo)
    fixed = state.experiments[0]
    check = next(c for c in state.checks if c.experiment_id)
    after = assessment(state, e.root, fixed, check)
    assert retained['before']['gap_ids'] and not after['gap_ids']
    assert retained['before']['interpretation_citations']['current'] and not after['interpretation_citations']['current']
    assert after['comparisons'] == retained['before']['comparisons']
    e.checkpoint('test_reuse')
    current_view(state, e.root)
    render_report(state, e.root)
    target_receipts(state, e.root, {check.id:[1]})
    sub, _ = opinion(state.model_dump(mode='json'))
    (e.root/'draft'/'reuse.json').write_text(json.dumps(sub))
    code = '''import json, sys
from pathlib import Path
from consensus_assurance.workflow import experiments
from consensus_assurance.workflow.audit import validate_submission
from consensus_assurance.workflow.history import load_analysis
from consensus_assurance.adapters.runners.python import PythonBackend
def unexpected(check):
    raise AssertionError('Independent validation reparsed finalized stdout')
experiments.extract_events = unexpected
root = Path(sys.argv[1])
print(json.dumps(validate_submission(load_analysis(root/'state.json'), root, 'reuse.json', PythonBackend())))
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(e.root)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['valid']
    assert parsed == [check.id] and state.usage['experiments'] == 1
    assert (e.root/'logs'/check.id/'observations.json').read_bytes() == retained['bytes']



def test_executed_report_archive_is_portable(tmp_path):
    e, repo = engine_for(tmp_path, [combined, opinion, stop])
    state = e.start(repo)
    clone = tmp_path / 'moved'
    shutil.copytree(e.root, clone)
    original = e.root.with_name('unavailable')
    e.root.rename(original)
    from consensus_assurance.adapters.storage.files import Store
    import re
    saved = Store(clone).load()
    assert saved == state
    report = render_report(saved, clone).read_text()
    check = next(c for c in saved.checks if c.experiment_id)
    observation = f'logs/{check.id}/observations.json'
    assert observation in report and json.loads((clone / observation).read_text())['events'][1]['value'] == 0
    assert str(original) not in report and str(e.root) not in report
    for link in re.findall(r'\]\(([^)]+)\)', report):
        assert (clone / link).is_file(), link
