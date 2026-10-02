from pathlib import Path
s=Path('snapshot_campaign_test.go').read_text()
s=s.replace('TestAssuranceSnapshotCampaignBarrier','TestAssuranceSnapshotOldConfiguration').replace('snapshot-campaign-1','snapshot-old-config-1')
s=s.replace('            if msg.To<1 || msg.To>3','            if msg.To==4 { continue } // Offline learner: transport drops its actual messages.\n            if msg.To<1 || msg.To>3')
s=s.replace('c.nodes[0].Propose([]byte("old-normal"))','c.nodes[0].ProposeConfChange(pb.ConfChange{Type:pb.ConfChangeAddLearnerNode,NodeID:4})')
s=s.replace('if ent.Type!=pb.EntryNormal {t.Fatal("older batch includes configuration")}','if ent.Type!=pb.EntryConfChange {t.Fatal("older batch is not the configuration entry")}')
a=s.index('    for _,payload:=range []string{"new-normal-a","new-normal-b"}')
b=s.index('    c.snapshotIndex=c.applied[0]',a)
s=s[:a]+'''    if err:=c.nodes[0].ProposeConfChange(pb.ConfChange{Type:pb.ConfChangeRemoveNode,NodeID:4});err!=nil {t.Fatal(err)}
    c.drain(all)
    if err:=c.nodes[0].Propose([]byte("post-remove-normal"));err!=nil {t.Fatal(err)}
    c.drain(all)
'''+s[b:]
a=s.index('        before:=c.nodes[2].BasicStatus()')
b=s.index('    assuranceEmit(map[string]interface{}{"event":"history_finished"',a)
s=s[:a]+'''        st:=c.nodes[2].Status()
        _,hasLearner4:=st.Config.Learners[4]
        assuranceEmit(map[string]interface{}{"event":"configuration_observed","request":c.request,"phase":phase,"node":3,"snapshot_index":c.snapshotIndex,"snapshot_completed":c.snapshotCompleted,"old_apply_completed":len(c.applyQ[2])==0,"current_learners":st.Config.Learners,"has_learner_4":hasLearner4,"snapshot_learners":snap.Metadata.ConfState.Learners,"applied":st.Applied,"app_applied":c.applied[2],"commit":st.Commit,"term":st.Term})
    }
'''+s[b:]
Path('snapshot_old_config_test.go').write_text(s)
