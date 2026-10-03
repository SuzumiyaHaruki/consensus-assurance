package logdb

import (
 "encoding/json"
 "errors"
 "fmt"
 "testing"
 "github.com/lni/dragonboat/v3/config"
 "github.com/lni/dragonboat/v3/internal/logdb/kv"
 "github.com/lni/dragonboat/v3/internal/vfs"
 pb "github.com/lni/dragonboat/v3/raftpb"
)

type assuranceFailReadKV struct { kv.IKVStore; fail bool; failures int }
func (k *assuranceFailReadKV) GetValue(key []byte, op func([]byte) error) error {
 if k.fail { k.fail=false; k.failures++; return errors.New("assurance injected non-notfound read error") }
 return k.IKVStore.GetValue(key,op)
}
func assuranceBatchEvent(v map[string]interface{}) { b,e:=json.Marshal(v);if e!=nil {panic(e)};fmt.Println("CA_EVENT "+string(b)) }
func TestAssuranceBatchReadError(t *testing.T) {
 for _,fail:=range []bool{false,true} { t.Run(fmt.Sprintf("fault_%v",fail),func(t *testing.T){
  fs:=vfs.GetTestFS()
  dir:=fmt.Sprintf("assurance-batch-read-%v",fail)
  if err:=fs.MkdirAll(dir,0755);err!=nil {t.Fatal(err)}
  defer fs.RemoveAll(dir)
  cfg:=config.GetDefaultLogDBConfig()
  var wrapper *assuranceFailReadKV
  factory:=func(c config.LogDBConfig, cb kv.LogDBCallback, d,w string, f vfs.IFS)(kv.IKVStore,error){
   store,err:=newDefaultKVStore(c,cb,d,w,f)
   if err!=nil{return nil,err}
   wrapper=&assuranceFailReadKV{IKVStore:store};return wrapper,nil
  }
  db,err:=openRDB(cfg,nil,dir,dir,true,fs,factory);if err!=nil {t.Fatal(err)}
  ctx:=newContext(cfg.SaveBufferSize,cfg.MaxSaveBufferSize)
  initial:=[]pb.Entry{{Index:1,Term:1},{Index:2,Term:1},{Index:3,Term:1}}
  err=db.saveRaftState([]pb.Update{{ClusterID:1,NodeID:1,State:pb.State{Term:1,Commit:3},EntriesToSave:initial}},ctx)
  if err!=nil {t.Fatal(err)}
  ctx.Destroy()
  if err:=db.kvs.Close();err!=nil {t.Fatal(err)}
  // Reopening establishes the uncached merge path without mutating target caches.
  db,err=openRDB(cfg,nil,dir,dir,true,fs,factory);if err!=nil {t.Fatal(err)}
  defer db.kvs.Close()
  be:=db.entries.(*batchedEntries)
  before,ok:=be.getBatchFromDB(1,1,0);if !ok {t.Fatal("initial batch absent")}
  assuranceBatchEvent(map[string]interface{}{"event":"before","fault":fail,"count":len(before.Entries),"first":before.Entries[0].Index,"last":before.Entries[len(before.Entries)-1].Index})
  ctx=newContext(cfg.SaveBufferSize,cfg.MaxSaveBufferSize);defer ctx.Destroy()
  wrapper.fail=fail
  err=db.saveRaftState([]pb.Update{{ClusterID:1,NodeID:1,EntriesToSave:[]pb.Entry{{Index:4,Term:1}}}},ctx)
  msg:="";if err!=nil {msg=err.Error()}
  // Fault injection ends after its one read; inspect bytes from the real store.
  after,exists:=be.getBatchFromDB(1,1,0)
  indices:=[]uint64{};for _,e:=range after.Entries {indices=append(indices,e.Index)}
  assuranceBatchEvent(map[string]interface{}{"event":"after","fault":fail,"injected":wrapper.failures,"save_error":msg,"exists":exists,"indices":indices})
 }) }
}
