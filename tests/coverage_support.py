"""Task-aware synthetic backend for exercising inquiry scheduling, not discovery quality."""
import json
import sys
from pathlib import Path
from consensus_assurance.adapters.agents.backend import MockAgent
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.core.types import Origin
from consensus_assurance.core.proposals import Discovery, ClaimDraft, BindingDraft, RelationDraft, UnitDraft, GraphPatch


def delivery_graph(context, wrong=False):
    material=next(m for m in context['materials'] if m['id']=='z_delivery.py:141:142')
    note=next(m for m in context['materials'] if m['file']=='service_notes.md')
    scope={'description':'Synthetic memory-mode completion, no crash claim','assumptions':[],'excluded':['Production protocols'],'parameters':{}}
    basis={'behavior_ids':[material['id']],'expectation_ids':[note['id']],'binding_ids':['delivery_binding'],'derivation':'The selected memory mode promises acceptance; the implementation returns accepted without a persistence step','applicability':'Memory mode only','unresolved':[],'conflicts':[],'alternatives':[]}
    goal=ClaimDraft(id='delivery_goal',kind='goal',description='The returned result satisfies the configured completion responsibility',source_ids=[note['id']],scope=scope,pending=[],grounding=basis)
    obligation=ClaimDraft(id='delivery_obligation',kind='obligation',description='Return in memory mode requires persistence' if wrong else 'Return in memory mode requires acceptance',source_ids=[note['id'],material['id']],scope=scope,pending=[],grounding=basis)
    binding=BindingDraft(id='delivery_binding',claim_id=obligation.id,material_id=material['id'],symbol='deliver',start_line=141,end_line=142,description='Actual memory acceptance result',pending=[])
    edge=RelationDraft(id='delivery_support',source=goal.id,target=obligation.id,kind='depends_all',group=None,rationale='The selected configured contract determines completion responsibility',pending=[],grounding=basis)
    unit=UnitDraft(id='delivery_unit',goal_ids=[goal.id],obligation_ids=[obligation.id],binding_ids=[binding.id],relation_ids=[edge.id],scope=scope,rationale='Investigate a second responsibility',goal_observable=False)
    return GraphPatch(claims=[goal,obligation],bindings=[binding],relations=[edge],units=[unit],rationale='Actual newly read completion source supports candidate goals')


class CoverageAgent(MockAgent):
    def __init__(self, responses, wrong=False, weak=False):
        super().__init__()
        self.source_responses=responses;self.wrong=wrong;self.weak=weak
    def probe(self,runner):
        return {'available':True,'version':'task-aware-mock/1','checks':[],'reason':'Explicit controlled coverage fixture'}
    def analyze(self,runner,prompt,directory,snapshot_id,timeout,response_type):
        context=json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])
        name=response_type.__name__
        self.cursor+=1
        note=next((m for m in context.get('materials',[]) if m['file']=='service_notes.md'),None)
        request={'file':'z_delivery.py','start_line':141,'end_line':142,'reason':'Read the unexamined result delivery implementation'}
        if name=='ReadingPlan':
            response={'requests':[{'file':'README.md','start_line':1,'end_line':5,'reason':'Read actual initial contract'}]+([request] if self.wrong else []),'rationale':'Initial fixture reading intentionally favors the counter region'}
        elif name=='Discovery':
            if self.wrong:
                graph=delivery_graph(context,True)
                response={'understanding':'A deliberately misread candidate, to be corrected from actual material','selection_rationale':'Check the result contract',**graph.model_dump(mode='json')}
                response.pop('expected_versions');response.pop('rationale')
                response['responsibilities']=[{'id':'delivery','description':'Return configured results','source_ids':[note['id']],'claim_ids':['delivery_goal','delivery_obligation'],'applicability':'Current memory configuration'}]
            else:
                response=json.loads(json.dumps(self.source_responses[1]))
                response['relations']=[r for r in response['relations'] if r['id']!='input_dependency']
                response['units'][0]['relation_ids'].remove('input_dependency')
                response['responsibilities']=[{'id':'counter','description':'Maintain finite counter state','source_ids':['README.md:1:5'],'claim_ids':['capacity_goal','step_obligation'],'applicability':'Serial fixture calls'},
                    {'id':'delivery','description':'Return configured results','source_ids':[note['id']],'claim_ids':[],'questions':['Actual result producer not yet read'],'applicability':'Memory configuration'}]
                response['reading_requests']=[request]
        elif name=='ExplorationReply':
            have=any(m['id']=='z_delivery.py:141:142' for m in context['materials'])
            existing=any(c['id']=='delivery_goal' for c in context['claims'])
            if not have:
                response={'understanding':'Missing another responsibility source','requests':[request],'responsibilities':[],'patch':{'rationale':'Read before proposing'},'limitations':[]}
            elif not existing:
                patch=delivery_graph(context)
                role=next(r for r in context['responsibilities'] if r['id']=='delivery').copy()
                role.update(claim_ids=['delivery_goal','delivery_obligation'],questions=[],source_ids=[note['id'],'z_delivery.py:141:142'])
                response={'understanding':'Another actual responsibility has now been read','responsibilities':[role],'patch':patch.model_dump(mode='json'),'limitations':['This fixture does not establish a complete system inventory']}
            else:
                response={'understanding':'The supplied regions have candidate coverage; other unknown duties remain possible','responsibilities':[],'patch':{'rationale':'No further supported additions in this bounded fixture'},'limitations':['No exhaustive coverage claim']}
        elif name=='ReviewReply':
            items=[];revision=None;exploration=[]
            for obj in context['target_objects']:
                source_ids=obj.get('source_ids') or obj.get('grounding',{}).get('behavior_ids') or ['README.md:1:5']
                aspect='applicability' if obj.get('kind') in {'goal','obligation','assumption'} else 'checker_correspondence' if obj.get('path') else 'decomposition'
                status='no_issue_found';explanation='Actual supplied responsibilities agree with the scoped candidate; this is not a proof'
                if obj.get('description')=='Return in memory mode requires persistence':
                    status='revision_needed';explanation='service_notes.md explicitly promises acceptance in memory mode, not persistence'
                    changed=ClaimDraft(**{k:v for k,v in obj.items() if k in ClaimDraft.model_fields});changed.description='Return in memory mode requires acceptance'
                    basis=changed.grounding.model_dump(mode='json')
                    revision={'kind':'F2','rationale':explanation,'evidence_ids':[note['id']],'target_ids':[obj['id']],'relation_ids':[],'new_basis':explanation,'graph':None,'bundle':None,
                        'patch':{'claims':[changed.model_dump(mode='json')],'expected_versions':{obj['id']:obj['version']},'rationale':explanation},'old_judgment':obj['description'],'new_judgment':changed.description,'grounding':basis}
                if self.weak and context['task']['trigger'].startswith('after_search') and obj['id']=='step_obligation':
                    status='disputed';explanation='The local bound holds but does not establish the delivery handoff responsibility'
                    exploration=[{'reason':'Investigate the counter-to-result handoff even though the local invariant held','responsibility_ids':['delivery'],'requests':[request]}]
                items.append({'target_id':obj['id'],'aspect':aspect,'status':status,'source_ids':source_ids,'explanation':explanation,'alternatives':'Different configured completion contracts can have different responsibilities','counterexample_reasoning':'A local counter bound alone cannot establish a returned-result contract','limitations':[]})
            for obj in context['target_objects']:
                if obj.get('kind')=='obligation':
                    original=next(i for i in items if i['target_id']==obj['id'])
                    items.append({**original,'aspect':'decomposition'})
            response={'items':items,'revision':revision,'exploration_requests':exploration,'limitations':[]}
        elif name=='BuildReply':
            response={'bundle':self.source_responses[2],'gap':''}
        else:
            raise AssertionError('Unexpected task '+name)
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
