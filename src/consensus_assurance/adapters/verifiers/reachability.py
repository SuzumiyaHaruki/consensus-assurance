"""Finite reachability via an auxiliary negated-state invariant, never a protocol violation."""
from pathlib import Path
import shutil
from consensus_assurance.core.types import ReachabilityResult, CheckRun, uid
from .input_identity import execution_fingerprint


def check_requirement(verifier,runner,model,bundle,requirement,timeout):
    if execution_fingerprint(model)!=model.search_fingerprint:
        check=CheckRun(action='reachability',cwd=str(runner.root),snapshot_id=model.snapshot_id,model_id=model.id,reason='Model search inputs changed; reachability not executed')
        return ReachabilityResult(model_id=model.id,requirement_id=requirement.id,check_id=check.id,status='unknown',search_fingerprint=model.search_fingerprint,reason=check.reason),check
    directory=runner.root/'reachability'/uid();directory.mkdir(parents=True)
    shutil.copyfile(Path(model.path).parent/'Behavior.tla',directory/'Behavior.tla')
    source=directory/'Reachability.tla'
    source.write_text('---- MODULE Reachability ----\nEXTENDS Behavior\nTriggerNotReached == ~('+requirement.operator+')\n====\n')
    init,next_action='Init','Next'
    if requirement.sequence:
        count=len(requirement.sequence);identity=requirement.identity_operator
        steps=requirement.sequence
        initial=f"CovInit == Init /\\ progress \\in {{0, IF {steps[0]} THEN 1 ELSE 0}} /\\ owner = {identity}"
        transitions=["UNCHANGED <<progress, owner>>"]
        for index,predicate in enumerate(steps):
            transitions.append(f"(/\\ progress = {index} /\\ {predicate}' /\\ progress' = {index+1} /\\ "+(f"owner' = {identity}'" if index==0 else f"owner = {identity}' /\\ UNCHANGED owner")+")")
        source.write_text('---- MODULE Reachability ----\nEXTENDS Behavior, Naturals\nVARIABLE progress, owner\n'+initial+'\nCovNext == Next /\\ (\n'+"\n \\/ ".join(transitions)+')\nTriggerNotReached == progress < '+str(count)+'\n====\n')
        init,next_action='CovInit','CovNext'
    cfg=directory/'Reachability.cfg'
    cfg.write_text('INIT '+init+'\nNEXT '+next_action+'\nCHECK_DEADLOCK FALSE\n'+('CONSTANTS\n'+bundle.constants+'\n' if bundle.constants.strip() else '')+'INVARIANT TriggerNotReached\n')
    adapted=model.model_copy(update={'path':str(source),'config_path':str(cfg),'checkers':[]})
    check=verifier.check(runner,adapted,timeout);check.action='reachability'
    check.parameters={'requirement_id':requirement.id,'operator':requirement.operator}
    status='unknown'
    if check.status.value=='completed':
        if check.outcome=='counterexample' and check.violated_invariant=='TriggerNotReached':status='reachable'
        elif check.outcome=='holds':status='unreachable'
    return ReachabilityResult(model_id=model.id,requirement_id=requirement.id,check_id=check.id,status=status,
        search_fingerprint=model.search_fingerprint,reason='Finite trigger search; an auxiliary counterexample is a reachability witness, not an implementation violation'),check
