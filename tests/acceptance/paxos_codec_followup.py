"""Manual directed follow-up; never loaded by autonomous runtime discovery."""
import argparse
import json
import time
from pathlib import Path

from consensus_assurance.core.config import Config
from consensus_assurance.core.types import (
    Activity, Analysis, AuditQuestion, Behavior, ConsensusAuditSpec, Fact, Grounding,
    QuestionCandidate, ReadRequest, Scope, TargetProfile,
)
from consensus_assurance.core.proposals import (
    BindingDraft, ClaimDraft, Comparison, Derivation, DirectCheckPlan,
    EventMonitor, EventRequirement, Harness, ObservableProperty,
)
from consensus_assurance.registry import assemble
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.adapters.runners.experiment import extract_events
from consensus_assurance.workflow.engine import Engine, FRAMEWORK_REVISION
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.workflow.audit_spec import accept
from consensus_assurance.workflow.discovery import accept_derivation, active_candidate
from consensus_assurance.workflow.direct_checks import save_plan, execute, assess
from consensus_assurance.workflow.graph import select_unit

TARGET_COMMIT = "35c69365f1c7737a08e237bfbaf828ee68897080"
PARENT_CANDIDATE = "2b3f14578ed446da9d80c43205b152ca"
SOURCE_RANGES = [
    ("paxos/paxos.go", 24, 163),
    ("paxos/paxos.go", 326, 352),
    ("paxos/defs.go", 427, 558),
    ("replica/replica.go", 215, 227),
    ("replica/replica.go", 416, 471),
    ("rpc/rpc.go", 1, 48),
    ("state/state.go", 1, 254),
]
HARNESS = r'''package paxos

import (
    "bufio"
    "bytes"
    "encoding/hex"
    "encoding/json"
    "fmt"
    "testing"
    base "github.com/imdea-software/swiftpaxos/replica"
    fastrpc "github.com/imdea-software/swiftpaxos/rpc"
    "github.com/imdea-software/swiftpaxos/state"
)

func assayEvent(kind, variant string, values map[string]interface{}) {
    payload := map[string]interface{}{"event":kind,"operation":"commit-17-"+variant,"participant":"0-to-1","context":"ballot-43","metadata":map[string]interface{}{"variant":variant,"legal":true},"state":values}
    raw, _ := json.Marshal(payload)
    fmt.Println("CA_EVENT "+string(raw))
}

func TestAssuranceCommitWire(t *testing.T) {
    command := []state.Command{{Op:state.PUT,K:7,V:state.Value("abc")}}
    for _, variant := range []string{"full", "short", "actual"} {
        var wire bytes.Buffer
        baseReplica := &base.Replica{N:2, Id:0, Alive:[]bool{false,true}, PreferredPeerOrder:[]int32{1,0}, PeerWriters:[]*bufio.Writer{nil,bufio.NewWriter(&wire)}, RPC:fastrpc.NewTableId(30)}
        replica := &Replica{Replica:baseReplica}
        replica.commitRPC=baseReplica.RPC.Register(new(Commit),make(chan fastrpc.Serializable,1))
        replica.commitShortRPC=baseReplica.RPC.Register(new(CommitShort),make(chan fastrpc.Serializable,1))
        switch variant {
        case "full": replica.SendMsg(1,replica.commitRPC,&Commit{LeaderId:0,Instance:17,Ballot:43,Command:command})
        case "short": replica.SendMsg(1,replica.commitShortRPC,&CommitShort{LeaderId:0,Instance:17,Ballot:43,Count:int32(len(command))})
        case "actual": replica.bcastCommit(17,43,command)
        }
        replica.SendMsg(1,replica.commitRPC,&Commit{LeaderId:0,Instance:18,Ballot:44,Command:command})
        data:=wire.Bytes()
        assayEvent("sent",variant,map[string]interface{}{"ballot":43,"next_code":int(replica.commitRPC),"wire_hex":hex.EncodeToString(data)})
        reader:=bytes.NewReader(data)
        code,_:=reader.ReadByte()
        pair,registered:=baseReplica.RPC.Get(code)
        if !registered { t.Fatalf("unregistered first code %d",code) }
        obj:=pair.Obj.New()
        before:=reader.Len()
        err:=obj.Unmarshal(reader)
        consumed:=before-reader.Len()
        nextCode,nextError:=reader.ReadByte()
        decodedBallot:=int32(-1)
        switch decoded:=obj.(type) {
        case *Commit: decodedBallot=decoded.Ballot
        case *CommitShort: decodedBallot=decoded.Ballot
        }
        values:=map[string]interface{}{"code":int(code),"ballot":int(decodedBallot),"consumed":consumed,"next_code":int(nextCode),"remaining":reader.Len(),"decoder_error":fmt.Sprint(err),"next_error":fmt.Sprint(nextError)}
        assayEvent("decoded",variant,values)
    }
}'''


def source_id(file, first, last):
    return f"{file}:{first}:{last}"


def descriptive_spec(materials):
    origin = source_id("paxos/paxos.go", 326, 352)
    registration = source_id("paxos/paxos.go", 24, 163)
    decoder = source_id("paxos/defs.go", 427, 558)
    listener = source_id("replica/replica.go", 416, 471)
    send = Behavior(id="paxos_commit_broadcast", primary_activity="A1",
        execution_owner="Paxos handler calling bcastCommit and synchronous SendMsg",
        protocol_context="One local commit broadcast to a selected alive peer",
        trigger="handleAcceptReply calls bcastCommit after setting local COMMITTED",
        source_ids=[origin, source_id("replica/replica.go",215,227)],
        external_effects=["bcastCommit sends &pc under commitShortRPC; SendMsg writes the code and invokes the supplied object's Marshal"],
        unknowns=["The original F3 report-support question remains unresolved"])
    receive = Behavior(id="paxos_peer_decode_short_commit", primary_activity="A1",
        execution_owner="Peer listener using the registered decoder",
        protocol_context="One code and payload boundary on the peer byte stream",
        trigger="RPC table lookup selects CommitShort.Unmarshal",
        produces_fact_ids=["paxos_short_commit_decoded"],source_ids=[registration,decoder,listener,source_id("rpc/rpc.go",1,48)],
        unknowns=["Network delivery and a complete protocol prehistory are outside this local check"])
    fact = Fact(id="paxos_short_commit_decoded",
        meaning="A registered CommitShort decoder consumed sixteen bytes into a fresh object; its fields describe those bytes, not automatically the sender's intended ballot",
        identity={"stream":"peer and message position","object":"decoded CommitShort"},
        validity_context="A selected message code and finite stream with sufficient bytes",
        established_by=[receive.id],representation=["CommitShort fields"],
        durability="transient",recovery="No restart guarantee is asserted",
        source_ids=[decoder,listener],unknowns=["The downstream delivery and full protocol outcome remain unverified"])
    return ConsensusAuditSpec(target_profile=TargetProfile(system_boundary="Selected Paxos package and built-in replica transport; manually projected from the saved v4 descriptive inventory",source_ids=[origin,registration,decoder,listener],unknowns=["Other activity classes remain outside this directed workset"]),
        activities=[Activity(class_id="A1",applicability="applicable",purpose="Message exchange for decision progression",realization_summary="The selected broadcast writes an RPC code and payload; the peer dispatches to a registered decoder",source_ids=[origin,registration,decoder,listener])] +
        [Activity(class_id=f"A{index}",applicability="unknown",purpose="Outside this directed local relation",realization_summary="The saved broader inventory is not imported into this local workset",unknowns=["Reassess in a separate question with its actual source"]) for index in range(2,8)],
        behaviors=[send,receive],facts=[fact],surfaces=[])


def plan(unit, grounding):
    identities=["operation","participant","context"]
    selected=Comparison(field="metadata.variant",value="actual")
    properties=[];monitors=[]
    for name, field, prior in [("BallotPreserved","state.ballot","sent.state.ballot"),("NextCodePreserved","state.next_code","sent.state.next_code")]:
        prop=ObservableProperty(checker_id=name,trigger=selected,assertion=Comparison(field=field,reference=prior),
            identity_fields=identities,description="Observed decoded field equals the corresponding observed send field for this correlated message")
        properties.append(prop)
        monitors.append(EventMonitor(id=name,checker_id=name,event="decoded",identity_fields=identities,
            conditions=[selected],assertion=prop.assertion,property=prop,binding_ids=unit.binding_ids,
            grounding=grounding,applicability_conditions=[Comparison(field="metadata.legal",value=True)]))
    return DirectCheckPlan(description="Full/full, short/short and actual broadcast pairing with one following message",claim_id=unit.obligation_ids[0],scope=unit.scope,binding_ids=unit.binding_ids,
        harness=Harness(kind="go_test",source=HARNESS,description="Calls real bcastCommit, SendMsg, registered decoders and Marshal/Unmarshal; buffers substitute only for network connections",prerequisite_events=["sent","decoded"],
            semantic_changes=["The peer connection is replaced by a byte buffer; scheduling, durability, peer receipt and full consensus history are excluded"],
            legality=grounding,legal_conditions=[Comparison(field="metadata.legal",value=True)],
            prerequisites=[EventRequirement(alias="sent",event="sent",conditions=[selected]),
                EventRequirement(alias="decoded",event="decoded",conditions=[selected]+[Comparison(field=k,reference="sent."+k) for k in identities])]),
        monitors=monitors,observable_properties=properties,
        uncertainties=["Manual directed scope and oracle have not received an independent semantic review; this observation cannot establish a whole-protocol violation"])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo",type=Path,required=True)
    parser.add_argument("--archive",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--tlc-jar",type=Path)
    args=parser.parse_args()
    archive=json.loads((args.archive/"state.json").read_text())
    if not any(c["id"]==PARENT_CANDIDATE and c["status"]=="active" for c in archive["question_candidates"]):
        raise ValueError("Saved unresolved parent candidate differs")
    if args.output.exists():raise FileExistsError(args.output)
    config=Config(execution_backend="go_module",target={"variant":"swiftpaxos_paxos","expected_module":"github.com/imdea-software/swiftpaxos","execution_package":"./paxos","harness_path":"paxos/assurance_generated_test.go","analysis_roots":["paxos","replica","rpc","state","go.mod","go.sum"]},
        agent_backend="codex",verifier_backend="tlc",tlc_jar=str(args.tlc_jar) if args.tlc_jar else None,
        execution_isolation="bwrap",allow_agent_materials=False,allow_experiments=True,
        directed_question="Check the code/payload decoder relation discovered during the saved Paxos F3 investigation",
        parameters={"manual_directed_followup":True,"parent_archive":args.archive.name,"parent_candidate_id":PARENT_CANDIDATE})
    implementation,agent,verifier,knowledge=assemble(config)
    engine=Engine(config,args.output,implementation,agent,verifier,knowledge)
    snapshot=capture(args.repo,engine.root/"source",analysis_roots=config.target.analysis_roots,expected_module=config.target.expected_module)
    if snapshot.commit!=TARGET_COMMIT:raise ValueError("Target commit differs from saved Paxos analysis")
    engine.state=Analysis(framework_revision=FRAMEWORK_REVISION,mode="real",analysis_mode="directed",config=config.model_dump(mode="json"),snapshot=snapshot)
    engine.budget=BudgetTracker(config.budget,engine.state)
    engine.runner.deadline=time.monotonic()+config.budget.total_seconds
    engine.checkpoint("manual_directed_source_created")
    requests=[ReadRequest(file=f,start_line=a,end_line=b,reason="Manual directed follow-up source dependency") for f,a,b in SOURCE_RANGES]
    engine.read(requests,purpose="depth",plan_id="directed-source",related_ids=[PARENT_CANDIDATE],reason="Source evidence for the local message representation relation")
    spec=descriptive_spec(engine.state.materials)
    accept(engine,spec)
    ids=[source_id(*row) for row in SOURCE_RANGES]
    q=AuditQuestion(question="Does the selected short-commit code preserve the broadcast's ballot and the next message boundary when the actual bcastCommit path is used?",
        importance="Incorrect decoded fields or stream position can change remote commit processing; the original support-attribution and decision consequences remain untested",
        source_ids=ids,activity_classes=["A1"],behavior_ids=[b.id for b in spec.behaviors],fact_ids=["paxos_short_commit_decoded"],
        obligation_relation_kind="consumption",disposition="ready_for_check",preferred_check="direct_test",objects=["one broadcast payload","registered CommitShort decoder"],
        contexts=["N=2; one alive peer; PUT command with a concrete key/value; synchronous buffered send"],
        event_paths=["actual bcastCommit -> SendMsg code and full payload -> registered decoder -> following message code"],
        counterevidence=["The correctly paired full/full and short/short controls may decode and frame correctly","Synchronous Marshal excludes post-return reference mutation for this single call"],
        unknowns=["Peer reception and full consensus prehistory are not established"],trigger_rationale="Compare actual decoded ballot and following code against independently recorded send fields")
    basis=Grounding(source_ids=[ids[1],ids[2],ids[3],ids[4]],expectation_ids=[ids[5]],binding_ids=["broadcast","short_decode"],
        derivation="The producer's selected code identifies the consumer's registered decoder; a successful message handoff must retain its intended ballot and following frame boundary for that consumer to interpret the message",
        applicability="One selected live peer, successful synchronous writes to a byte stream, registered short-commit decoder and enough payload bytes")
    scope=Scope(description="One finite local send/decode handoff plus two correctly paired controls",assumptions=["The byte buffer faithfully records successful synchronous writes"],
        excluded=["Network delivery timing","Full Paxos quorum history","Different decisions","Crash and disk faults"],parameters={"N":2,"instance":17,"ballot":43})
    claim=ClaimDraft(id="codec_relation",kind="obligation",description="For a successfully sent labeled commit message, the registered receiver decoder must preserve the sender's ballot and the next message boundary",source_ids=[ids[0],ids[1],ids[2],ids[3],ids[4],ids[5]],scope=scope,pending=[],grounding=basis)
    bindings=[
        BindingDraft(id="broadcast",material_id=ids[1],symbol="Replica.bcastCommit",start_line=326,end_line=352,description="Actual choice of code and serialized object",pending=[],associations=[{"claim_id":claim.id,"source_ids":[ids[1]],"rationale":"Direct producer for the checked handoff"}]),
        BindingDraft(id="short_decode",material_id=ids[2],symbol="CommitShort.Unmarshal",start_line=546,end_line=558,description="Registered receiver interpretation",pending=[],associations=[{"claim_id":claim.id,"source_ids":[ids[2]],"rationale":"Direct consumer for the checked handoff"}]),
    ]
    engine.state.question_candidates.append(QuestionCandidate(question=q,parent_candidate_id=PARENT_CANDIDATE,fork_reason="Independent codec handoff discovered while the original F3 support question remained unresolved",material_ids=ids))
    reply=Derivation(obligation=claim,bindings=bindings,audit_question=q,selection_rationale="The local producer/decoder relation has actual source and a finite observable oracle; its broader consequence remains deferred")
    accept_derivation(engine,reply,"manual-directed-derivation")
    unit=select_unit(engine.state)
    direct=plan(unit,basis)
    artifact=save_plan(engine,unit,direct,"manual-directed-plan")
    engine.state.active_direct_check_id=artifact.id
    check=execute(engine,artifact,direct)
    events=extract_events(check)
    result=assess(engine.state,unit,artifact,direct,check,events)
    write_json(engine.root/"directed-followup.json",{"manual_inputs":["principal Fact and source ranges projected from saved descriptive inventory","bounded question, obligation, binding associations, test harness and oracle authored by a human-directed acceptance script"],"parent_archive":args.archive.name,"parent_candidate_id":PARENT_CANDIDATE,"source_commit":snapshot.commit,"check_id":check.id,"events":events,"assessment":result})
    engine.state.stop_reason="Directed local check completed; original candidate remains unresolved in the parent archive"
    engine.checkpoint("directed_followup_completed")
    print(engine.root/"directed-followup.json")


if __name__=="__main__":main()
