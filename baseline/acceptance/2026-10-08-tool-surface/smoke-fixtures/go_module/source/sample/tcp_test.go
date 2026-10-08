package sample
import ("io"; "net"; "testing"; "time")
func TestTCPRoundtrip(t *testing.T) {
    const wantReply = "wrong"
    listener, err := net.Listen("tcp", "127.0.0.1:0"); if err != nil { t.Fatal(err) }; defer listener.Close()
    client, err := net.DialTimeout("tcp", listener.Addr().String(), 5*time.Second); if err != nil { t.Fatal(err) }; defer client.Close()
    server, err := listener.Accept(); if err != nil { t.Fatal(err) }; defer server.Close()
    if err = client.SetDeadline(time.Now().Add(5*time.Second)); err != nil { t.Fatal(err) }
    if err = server.SetDeadline(time.Now().Add(5*time.Second)); err != nil { t.Fatal(err) }
    if _, err = client.Write([]byte("ping")); err != nil { t.Fatal(err) }
    request := make([]byte, 4); if _, err = io.ReadFull(server, request); err != nil { t.Fatal(err) }
    if _, err = server.Write([]byte("pong")); err != nil { t.Fatal(err) }
    reply := make([]byte, 4); if _, err = io.ReadFull(client, reply); err != nil { t.Fatal(err) }
    t.Logf("TCP_OBSERVED request=%s reply=%s", request, reply)
    if string(request) != "ping" { t.Fatalf("request mismatch: %q", request) }
    if string(reply) != wantReply { t.Fatalf("TCP_REPLY_ASSERTION: want %q, got %q", wantReply, reply) }
}
