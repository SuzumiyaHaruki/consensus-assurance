"""Agent requests and bounded field repairs with recoverable local originals."""
import json
from pathlib import Path
from consensus_assurance.core.types import CheckRun, uid
from consensus_assurance.adapters.storage.files import write_json
from .prompts import render
from .errors import Blocked
from .output_repair import OutputRepair, repair_targets, apply_replacements, repair_context


def ask(engine, kind, response_type, context, validator=None):
    if not engine.agent.mock and not engine.config.allow_agent_materials:
        raise Blocked('Agent material transmission disabled by configuration; no repository payload was sent')
    state = engine.state
    saved = state.pending_output_repair
    if saved and saved['task'] != kind:
        raise Blocked('A different output repair is pending; resume its recorded action first')
    limit = engine.config.budget.repeated_error_revisions
    while True:
        saved = state.pending_output_repair
        if saved and saved['attempt'] >= limit:
            raise Blocked('Structured response repair limit reached: ' + saved['error'])
        request_context = context
        schema = response_type
        if saved:
            schema = OutputRepair
            request_context = {'original_task':kind, 'response_type':response_type.__name__,
                'repair_targets':saved['targets'], 'validation_error':saved['error'],
                'related_context':saved.get('related_context',{}),
                'preservation':'Only replace reported fields; every other original field remains local and unchanged',
                'remaining_seconds':engine.budget.remaining()}
        directory = engine.root / 'agent' / (uid()+'-'+kind)
        prompt = render('retry' if saved else kind, request_context,
            engine.inquiry if kind in {'read','discover','F3','targeted_read','graph_patch','explore','semantic_review'} else '')
        payload = engine.action('agent:'+kind+(':repair' if saved else ''),'agent_calls',
            lambda:engine.agent.analyze(engine.runner,prompt,directory,state.snapshot.id,engine.budget.timeout(),schema),
            {'prompt':prompt,'response_type':schema.__name__})
        check = CheckRun.model_validate(payload[0]); check.parameters["agent_task"]=kind; engine.record(check)
        cwd = Path(check.cwd)
        errors=[]; original=None
        try:
            if payload[1] is None:
                if check.reason != 'Structured agent output is invalid':
                    raise Blocked(f'Agent blocked: {check.status.value}; {check.reason}')
                details=cwd/'validation-details.json'
                errors=json.loads(details.read_text()) if details.exists() else []
                decoded=cwd/'decoded-response.json'
                if decoded.exists(): original=json.loads(decoded.read_text())
                raise ValueError((cwd/'validation-error.txt').read_text() if (cwd/'validation-error.txt').exists() else check.reason)
            if saved:
                original=json.loads(Path(saved['original_path']).read_text())
                repaired=apply_replacements(original,saved['targets'],OutputRepair.model_validate(payload[1]))
                original=repaired
                response=response_type.model_validate(repaired)
            else:
                original=payload[1]
                response=response_type.model_validate(original)
            if validator: validator(response)
            write_json(cwd/'accepted-response.json',response)
            state.pending_output_repair=None
            return response,check
        except ValueError as exc:
            error=str(exc)
            if hasattr(exc,'errors'): errors=exc.errors(include_url=False,include_context=False)
            (cwd/'graph-validation-error.txt').write_text(error)
            if state.pending_action:
                state.action_history.append(state.pending_action.model_copy(deep=True));state.pending_action=None
            attempt=saved['attempt']+1 if saved else 0
            if saved and original is None:
                original=json.loads(Path(saved['original_path']).read_text())
            if original is None:
                raise Blocked('Unparseable output cannot be locally patched; raw output preserved: '+error)
            original_path=cwd/'repair-original.json';write_json(original_path,original)
            if attempt >= limit:
                targets=[]
            else:
                try: targets=repair_targets(original,errors,error,engine.config.budget.error_context_chars)
                except ValueError as localization:
                    raise Blocked(str(localization)) from exc
            state.pending_output_repair={'task':kind,'original_path':str(original_path),'targets':targets,'error':error,'attempt':attempt,
                'related_context':saved.get('related_context',{}) if saved else repair_context(original,targets,context,engine.config.budget.error_context_chars)}
            engine.checkpoint('output_repair_pending')
