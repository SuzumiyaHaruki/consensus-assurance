from pathlib import Path
s=Path('delayed_vote_test.go').read_text()
s=s.replace('if msg.Type==pb.MsgVoteResp && msg.To==1 {','if (msg.Type==pb.MsgVoteResp || msg.Type==pb.MsgPreVoteResp) && msg.To==1 {')
s=s.replace('if msg.Reject || hs.Term!=msg.Term || hs.Vote!=1','if msg.Reject || (msg.Type==pb.MsgVoteResp && (hs.Term!=msg.Term || hs.Vote!=1))')
s=s.replace('"event":"grant_captured","request":c.request,','"event":"grant_captured","type":msg.Type.String(),"request":c.request,')
s=s.replace('release(term,from uint64)','release(typ pb.MessageType,term,from uint64)').replace('if m.Term==term && m.From==from','if m.Type==typ && m.Term==term && m.From==from')
s=s.replace('TestAssuranceDelayedElectionGrants','TestAssuranceDelayedPreVoteGrant').replace('consecutive-campaigns-1','prevote-real-campaign-1').replace('AsyncStorageWrites:true,Logger:','AsyncStorageWrites:true,PreVote:true,Logger:')
a=s.index('    c.phase="first_campaign"');b=s.index('    for _,p:=range phases',a)
s=s[:a]+'''    c.phase="pre_campaign"
    before:=c.nodes[0].BasicStatus().Term
    if err:=c.nodes[0].Campaign();err!=nil {t.Fatal(err)}
    c.drain(all)
    if len(c.heldVotes)!=3 || c.nodes[0].BasicStatus().RaftState!=StatePreCandidate || c.nodes[0].BasicStatus().Term!=before {t.Fatal("pre-campaign prefix missing")}
    c.currentTerm=before+1
    c.phase="pre_majority"
    c.release(pb.MsgPreVoteResp,c.currentTerm,1)
    c.drain(all)
    c.release(pb.MsgPreVoteResp,c.currentTerm,2)
    c.drain(all)
    if len(c.heldVotes)!=4 || c.nodes[0].BasicStatus().Term!=c.currentTerm || c.nodes[0].BasicStatus().RaftState!=StateCandidate {t.Fatal("real campaign prefix missing")}
    phases:=[]struct{name string;typ pb.MessageType;term,from uint64}{
        {"delayed_pre_vote",pb.MsgPreVoteResp,c.currentTerm,3},
        {"real_self",pb.MsgVoteResp,c.currentTerm,1},
        {"real_peer_2",pb.MsgVoteResp,c.currentTerm,2},
        {"real_peer_3",pb.MsgVoteResp,c.currentTerm,3},
    }
'''+s[b:]
s=s.replace('c.release(p.term,p.from)','c.release(p.typ,p.term,p.from)').replace('"released_term":p.term,','"released_type":p.typ.String(),"released_term":p.term,')
Path('delayed_prevote_test.go').write_text(s)
