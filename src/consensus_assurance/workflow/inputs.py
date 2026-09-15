"""Search identity excludes experiments; code confirmation retains full artifact dependencies."""
from consensus_assurance.adapters.verifiers.input_identity import fingerprint, execution_fingerprint


def search_inputs(state, unit, bundle, config_text):
    selected=set(unit.binding_ids+unit.relation_ids+unit.goal_ids+unit.obligation_ids+[unit.id])
    return {'behavior':bundle.behavior,'properties':bundle.properties,'configuration':config_text,
        'scope':bundle.scope.model_dump(mode='json'),'constraints':[c.model_dump(mode='json') for c in bundle.constraints],
        'checkers':[c.model_dump(mode='json') for c in bundle.checker_specs()],
        'semantic_versions':{x.id:x.version for x in [*state.claims,*state.bindings,*state.relations,*state.units] if x.id in selected},
        'code':{b.id:{'file':b.file,'digest':b.content_digest,'symbol':b.symbol,'range':[b.start_line,b.end_line],'claim_id':b.claim_id} for b in state.bindings if b.id in unit.binding_ids}}


def reusable_search(state, model):
    if not model.search_fingerprint:return None
    if any(c.action=='model_check' and c.model_id==model.id for c in state.checks):return None
    for check in reversed(state.checks):
        if check.origin.value!=('mock' if state.mode=='mock' else 'executed'):continue
        if check.action!='model_check' or check.status.value!='completed' or check.outcome not in {'holds','counterexample'}:continue
        if check.search_fingerprint!=model.search_fingerprint or check.snapshot_id!=model.snapshot_id:continue
        if check.tool_version!=state.tools.get('verifier',check.tool_version):continue
        if not check.checker_results or any(r.outcome=='unknown' for r in check.checker_results):continue
        if any(e.check_id==check.id and e.applicability=='recheck_required' for e in state.evidence):continue
        return check
    return None
