"""Task-aware synthetic backend for exercising inquiry scheduling, not discovery quality."""
import json
import sys
from pathlib import Path
from consensus_assurance.adapters.agents.backend import MockAgent
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.core.types import Origin
from consensus_assurance.core.proposals import GraphDraft, ClaimDraft, BindingDraft, RelationDraft, UnitDraft, GraphPatch


def delivery_graph(context, wrong=False):
    material=next(m for m in context['materials'] if m['id']=='z_delivery.py:141:142')
    note=next(m for m in context['materials'] if m['file']=='service_notes.md')
    scope={'description':'Synthetic memory-mode completion, no crash claim','assumptions':[],'excluded':['Production protocols'],'parameters':{}}
    basis={'behavior_ids':[material['id']],'expectation_ids':[note['id']],'binding_ids':['delivery_binding'],'derivation':'The selected memory mode promises acceptance; the implementation returns accepted without a persistence step','applicability':'Memory mode only','unresolved':[],'conflicts':[],'alternatives':[]}
    goal=ClaimDraft(id='delivery_goal',kind='obligation',description='The returned result satisfies the configured completion responsibility',source_ids=[note['id']],scope=scope,pending=[],grounding=basis)
    obligation=ClaimDraft(id='delivery_obligation',kind='obligation',description='Return in memory mode requires persistence' if wrong else 'Return in memory mode requires acceptance',source_ids=[note['id'],material['id']],scope=scope,pending=[],grounding=basis)
    binding=BindingDraft(id='delivery_binding',claim_id=obligation.id,material_id=material['id'],symbol='deliver',start_line=141,end_line=142,description='Actual memory acceptance result',pending=[])
    edge=RelationDraft(id='delivery_support',source=goal.id,target=obligation.id,kind='depends_all',group=None,rationale='The selected configured contract determines completion responsibility',pending=[],grounding=basis)
    unit=UnitDraft(id='delivery_unit',obligation_ids=[obligation.id],binding_ids=[binding.id],relation_ids=[],scope=scope,rationale='Investigate a second responsibility',)
    return GraphPatch(claims=[obligation],bindings=[binding],relations=[],units=[unit],rationale='Actual newly read completion source supports candidate goals')


class CoverageAgent(MockAgent):
    def __init__(self, responses, wrong=False, weak=False):
        super().__init__()
        self.source_responses=responses;self.wrong=wrong;self.weak=weak
    def probe(self,runner):
        return {'available':True,'version':'task-aware-mock/1','checks':[],'reason':'Explicit controlled coverage fixture'}
    def analyze(self,runner,prompt,directory,snapshot_id,timeout,response_type):
        if response_type.__name__=='Discovery':
            self.descriptive_context=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])
            from regression_support import inventory_response
            return inventory_response(runner,prompt,directory,snapshot_id,timeout)
        context=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])
        name=response_type.__name__
        self.cursor+=1
        note=next((m for m in context.get('materials',[]) if m['file']=='service_notes.md'),None)
        request={'file':'z_delivery.py','start_line':141,'end_line':142,'reason':'Read the unexamined result delivery implementation'}
        if name=='ReadingPlan':
            response={'requests':[next(r for r in self.source_responses[0]['requests'] if r['file']=='README.md')]+([request] if self.wrong else []),'rationale':'Initial fixture reading intentionally favors the counter region'}
        elif name=='Derivation':
            if self.wrong:
                graph=delivery_graph({**context,'materials':self.descriptive_context['materials']},True)
                response=graph.model_dump(mode='json')
                response.pop('expected_versions');response.pop('rationale')
            else:
                response=json.loads(json.dumps(self.source_responses[1]))
                response['relations']=[r for r in response['relations'] if r['id']!='input_dependency']
                response['units'][0]['relation_ids']=[id for id in response['units'][0]['relation_ids'] if id!='input_dependency']
                response['reading_requests']=[request]
        elif name=='SpecRefinement':
            response={'understanding':'Controlled fixture retains explicit descriptive gaps','delta':{'rationale':'No descriptive change justified by this fixture'},'requests':[], 'limitations':['Finite synthetic coverage only']}
        elif name=='ReviewReply':
            items=[];revision=None
            for obj in context['target_objects']+([context['selected_unit']] if context.get('selected_unit',{}).get('id') in context['task']['target_ids'] else []):
                source_ids=obj.get('source_ids') or obj.get('grounding',{}).get('behavior_ids') or [context['materials'][0]['id']]
                contract=next(c for c in context['review_contract'] if c['target_id']==obj['id'])
                aspect=contract['required_aspects'][0]
                status='no_issue_found';explanation='Actual supplied responsibilities agree with the scoped candidate; this is not a proof'
                if obj.get('description')=='Return in memory mode requires persistence':
                    status='revision_needed';explanation='service_notes.md explicitly promises acceptance in memory mode, not persistence'
                    changed=ClaimDraft(**{k:v for k,v in obj.items() if k in ClaimDraft.model_fields});changed.description='Return in memory mode requires acceptance'
                    basis=changed.grounding.model_dump(mode='json')
                    revision={'kind':'F2','rationale':explanation,'evidence_ids':[note['id']],'target_ids':[obj['id']],'relation_ids':[],'new_basis':explanation,'graph':None,'bundle':None,
                        'patch':{'claims':[changed.model_dump(mode='json')],'expected_versions':{obj['id']:obj['version']},'rationale':explanation},'old_judgment':obj['description'],'new_judgment':changed.description,'grounding':basis,'changes':[{'target_id':obj['id'],'field':'description','old_value_json':json.dumps(obj['description']),'new_value_json':json.dumps(changed.description)}]}
                if self.weak and context['task']['trigger'].startswith('after_search') and bool(obj.get('bundle_path')):
                    status='disputed';explanation='The local bound holds but does not establish the delivery handoff responsibility'
                items.append({'target_id':obj['id'],'aspect':aspect,'status':status,'source_ids':source_ids,'limitations':[],'rationale':explanation + "\n" + 'Different configured completion contracts can have different responsibilities' + "\n" + 'A local counter bound alone cannot establish a returned-result contract'})
            for obj in context['target_objects']+([context['selected_unit']] if context.get('selected_unit',{}).get('id') in context['task']['target_ids'] else []):
                contract=next(c for c in context['review_contract'] if c['target_id']==obj['id'])
                original=next(i for i in items if i['target_id']==obj['id'])
                for aspect in contract['required_aspects'][1:]:items.append({**original,'aspect':aspect})
            resolved=[issue['id'] for issue in context.get('open_issues',[]) if any(i['target_id']==issue['target_id'] and i['aspect']==issue['aspect'] and i['status']=='no_issue_found' for i in items)]
            response={'items':items,'revision':revision,'limitations':[],'resolves_issue_ids':resolved,'resolution_rationale':'The corrected current configuration and cited materials address the prior interpretation' if resolved else ''}
        elif name=='BuildReply':
            response={'bundle':self.source_responses[2],'gap':''}
        else:
            raise AssertionError('Unexpected task '+name)
        if name=='Derivation':
            from regression_support import bounded_derivation
            response=bounded_derivation(response)
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'prompt.txt').write_text(prompt)
        write_json(directory/'response.json',response)
        write_json(directory/'decoded-response.json',response)
        check=runner.run([sys.executable,'-c','print("explicit task-aware mock response")'],directory,'agent',snapshot_id,timeout)
        check.origin=Origin.MOCK
        return check,response_type.model_validate(response)


def add_coverage_materials(repo):
    (repo/'service_notes.md').write_text('Memory mode promises acceptance on return. Durable mode promises persistence on return.\nResult delivery consumes accepted operations from state handling.\n')
    (repo/'z_delivery.py').write_text('\n'*140+'def deliver():\n    return "accepted"\n')


import os
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble

def setup_workflow(tmp_path,prepared,wrong=False,weak=False,tlc=None):
    repo,_,_,responses=prepared;add_coverage_materials(repo)
    config=Config(implementation='toy',agent_backend='mock',allow_experiments=False,tlc_jar=os.environ.get('TLC_JAR'))
    config.budget.agent_calls=20;config.budget.exploration_rounds=5;config.budget.semantic_reviews=6
    config.budget.audit_units=0 if wrong else 1
    config.budget.targeted_reads=6;config.budget.outer_reserve_seconds=1
    root=tmp_path/'inquiry-run'
    impl,_,verifier,knowledge=assemble(config)
    return repo,config,root,(impl,CoverageAgent(responses,wrong,weak),verifier,knowledge)
