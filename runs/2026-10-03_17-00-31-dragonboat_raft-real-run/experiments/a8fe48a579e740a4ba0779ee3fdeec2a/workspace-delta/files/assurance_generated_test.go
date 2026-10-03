package dragonboat
import("os";"os/exec";"path/filepath";"runtime";"testing")
func TestAssuranceBatchLauncher(t *testing.T){
 c:=exec.Command(filepath.Join(runtime.GOROOT(),"bin","go"),"test","-v","-count=1","-timeout=180s","-run","^TestAssuranceBatchReadError$","./internal/logdb")
 c.Stdout=os.Stdout;c.Stderr=os.Stderr;if e:=c.Run();e!=nil{t.Fatal(e)}
}
