package dragonboat

import (
	"fmt"
	"testing"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/fileutil"
	"github.com/lni/dragonboat/v3/internal/logdb"
	"github.com/lni/dragonboat/v3/internal/server"
	"github.com/lni/dragonboat/v3/internal/vfs"
	pb "github.com/lni/dragonboat/v3/raftpb"
)

// TestAssuranceLogDBShardRouting compares the cluster bucket the execution
// engine uses to assign clusters to a step worker with the partition id the
// sharded logdb derives from the same cluster id, for an expert configuration
// whose two counts differ, and records what the sharded logdb does with a
// raft-state batch assembled from a single step bucket.
func TestAssuranceLogDBShardRouting(t *testing.T) {
	expert := config.GetDefaultExpertConfig()
	expert.LogDB = config.GetTinyMemLogDBConfig()
	expert.Engine.ExecShards = 4
	expert.LogDB.Shards = 6
	cfg := config.NodeHostConfig{
		NodeHostDir:    "/assurance-shard-route",
		RaftAddress:    "localhost:9010",
		RTTMillisecond: 200,
		Expert:         expert,
	}
	fmt.Printf("CA_EVENT {\"event\":\"config\",\"exec_shards\":%d,\"logdb_shards\":%d,\"validate_error\":%q}\n",
		expert.Engine.ExecShards, expert.LogDB.Shards, errorText(cfg.Validate()))

	// newWorkReady builds the step-side partitioner with the execution shard
	// count only, while the sharded logdb builds its own partitioner from both
	// counts.
	stepP := server.NewFixedPartitioner(expert.Engine.ExecShards)
	dbP := server.NewDoubleFixedPartitioner(expert.Engine.ExecShards,
		expert.LogDB.Shards)
	for _, cid := range []uint64{1, 7, 9} {
		fmt.Printf("CA_EVENT {\"event\":\"routing\",\"cluster_id\":%d,\"step_bucket\":%d,\"logdb_partition\":%d}\n",
			cid, stepP.GetPartitionID(cid), dbP.GetPartitionID(cid))
	}

	fs := vfs.MemStrictFS
	dir := "/assurance-shard-route/logdb"
	if err := fileutil.MkdirAll(dir, fs); err != nil {
		t.Fatalf("mkdir failed %v", err)
	}
	ldb, err := logdb.NewDefaultFactory(fs).Create(cfg, nil, []string{dir}, nil)
	if err != nil {
		t.Fatalf("logdb creation failed %v", err)
	}
	defer func() {
		if err := ldb.Close(); err != nil {
			t.Errorf("logdb close failed %v", err)
		}
	}()

	save := func(name string, updates []pb.Update, workerID uint64) {
		msg := ""
		panicked := false
		func() {
			defer func() {
				if r := recover(); r != nil {
					panicked = true
					msg = fmt.Sprintf("%v", r)
				}
			}()
			if err := ldb.SaveRaftState(updates, workerID); err != nil {
				msg = fmt.Sprintf("error: %v", err)
			}
		}()
		fmt.Printf("CA_EVENT {\"event\":\"save\",\"case\":%q,\"worker_id\":%d,\"panicked\":%t,\"message\":%q}\n",
			name, workerID, panicked, msg)
	}
	// A single cluster whose logdb partition differs from its step bucket.
	save("single", []pb.Update{{ClusterID: 9}}, 2)
	// Two clusters of one bucket that share a logdb partition.
	save("same_partition", []pb.Update{{ClusterID: 1}, {ClusterID: 7}}, 2)
	// The batch step worker 2 assembles for bucket 1 when clusters 1 and 9
	// both produce updates in the same iteration.
	save("mixed_partition", []pb.Update{{ClusterID: 1}, {ClusterID: 9}}, 2)
}

func errorText(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
