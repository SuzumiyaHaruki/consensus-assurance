package logdb

import (
 "bytes"
 "encoding/json"
 "errors"
 "fmt"
 "path/filepath"
 "testing"

 "github.com/lni/dragonboat/v3/config"
 "github.com/lni/dragonboat/v3/internal/logdb/kv"
 "github.com/lni/dragonboat/v3/internal/vfs"
 pb "github.com/lni/dragonboat/v3/raftpb"
)

func assuranceStorageEvent(event string, fields map[string]interface{}) {
 fields["event"] = event
 fields["operation"] = "cold-append-4"
 fields["cluster"] = uint64(11)
 fields["node"] = uint64(1)
 data, err := json.Marshal(fields)
 if err != nil { panic(err) }
 fmt.Println("CA_EVENT " + string(data))
}

type assuranceReadErrorStore struct {
 kv.IKVStore
 key []byte
 armed bool
 hits int
}
func (s *assuranceReadErrorStore) GetValue(key []byte, op func([]byte) error) error {
 if s.armed && bytes.Equal(key, s.key) {
  s.armed = false
  s.hits++
  assuranceStorageEvent("lookup_failed", map[string]interface{}{"policy":"one-read-error"})
  return errors.New("injected non-not-found storage read error")
 }
 return s.IKVStore.GetValue(key, op)
}

type assuranceStoredEntry struct {
 Index uint64 `json:"index"`
 Term uint64 `json:"term"`
 Cmd string `json:"cmd"`
}
func assuranceStoredBatch(t *testing.T, r *db, key []byte) []assuranceStoredEntry {
 t.Helper()
 var batch pb.EntryBatch
 err := r.kvs.GetValue(key, func(data []byte) error {
  if len(data)==0 { return errors.New("batch missing during observation") }
  return batch.Unmarshal(data)
 })
 if err != nil { t.Fatal(err) }
 if len(batch.Entries)>1 { batch=restoreBatchFields(batch) }
 result:=make([]assuranceStoredEntry,0,len(batch.Entries))
 for _, e:=range batch.Entries { result=append(result,assuranceStoredEntry{e.Index,e.Term,string(e.Cmd)}) }
 return result
}
func assurancePrefix(entries []assuranceStoredEntry) string {
 prefix:=make([]assuranceStoredEntry,0)
 for _,e:=range entries { if e.Index<4 { prefix=append(prefix,e) } }
 data,err:=json.Marshal(prefix)
 if err!=nil {panic(err)}
 return string(data)
}
func TestAssuranceColdBatchAppendReadError(t *testing.T) {
 if batchSize<=4 { t.Fatal("requires indexes 1 through 4 in the same unaligned batch") }
 dir:=filepath.Join(t.TempDir(),"logdb")
 key:=newKey(maxKeySize,nil)
 key.SetEntryBatchKey(11,1,getBatchID(4))
 batchKey:=append([]byte(nil),key.Key()...)
 var current *db
 var fault *assuranceReadErrorStore
 defer func(){if current!=nil { if err:=current.close();err!=nil {t.Error(err)} }}()
 open:=func(){
  factory:=func(cfg config.LogDBConfig, cb kv.LogDBCallback, d,w string, fs vfs.IFS)(kv.IKVStore,error){
   underlying,err:=newDefaultKVStore(cfg,cb,d,w,fs)
   if err!=nil{return nil,err}
   fault=&assuranceReadErrorStore{IKVStore:underlying,key:batchKey}
   return fault,nil
  }
  var err error
  current,err=openRDB(config.GetTinyMemLogDBConfig(),nil,dir,"",true,vfs.DefaultFS,factory)
  if err!=nil {t.Fatal(err)}
 }
 closeDB:=func(){r:=current;current=nil;if err:=r.close();err!=nil {t.Fatal(err)}}
 save:=func(entries []pb.Entry)error{
  ctx:=newContext(4096,1024*1024)
  defer ctx.Destroy()
  ctx.Reset()
  return current.saveRaftState([]pb.Update{{ClusterID:11,NodeID:1,State:pb.State{Term:1,Commit:3},EntriesToSave:entries}},ctx)
 }
 open()
 old:=[]pb.Entry{{Index:1,Term:1,Cmd:[]byte("one")},{Index:2,Term:1,Cmd:[]byte("two")},{Index:3,Term:1,Cmd:[]byte("three")}}
 if err:=save(old);err!=nil {t.Fatal(err)}
 baseline:=assuranceStoredBatch(t,current,batchKey)
 if len(baseline)!=3 {t.Fatal("initial storage incomplete")}
 for i,e:=range baseline {if e.Index!=old[i].Index || e.Term!=old[i].Term || e.Cmd!=string(old[i].Cmd){t.Fatal("initial storage differs")}}
 closeDB()
 open()
 before:=assuranceStoredBatch(t,current,batchKey)
 if assurancePrefix(before)!=assurancePrefix(baseline) {t.Fatal("reopen changed prefix before fault")}
 if _,ok:=current.cs.getLastBatch(11,1,pb.EntryBatch{});ok {t.Fatal("reopen cache unexpectedly populated")}
 assuranceStorageEvent("append_admitted",map[string]interface{}{"prefix":assurancePrefix(before),"policy":"one-read-error","cold_cache":true,"batch_size":batchSize})
 fault.armed=true
 err:=save([]pb.Entry{{Index:4,Term:1,Cmd:[]byte("four")}})
 fault.armed=false
 if fault.hits!=1 {t.Fatalf("fault delivery count %d",fault.hits)}
 returnedError:=""
 if err!=nil {returnedError=err.Error()}
 closeDB()
 open()
 after:=assuranceStoredBatch(t,current,batchKey)
 assuranceStorageEvent("append_observed",map[string]interface{}{"success":err==nil,"returned_error":returnedError,"prefix":assurancePrefix(after),"stored_entries":after})
 closeDB()
}
