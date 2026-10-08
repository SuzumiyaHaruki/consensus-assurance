use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::time::Duration;
#[test]
fn tcp_roundtrip() {
    let want_reply = "pong";
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let mut client = TcpStream::connect_timeout(&listener.local_addr().unwrap(), Duration::from_secs(5)).unwrap();
    let (mut server, _) = listener.accept().unwrap();
    client.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    server.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    client.write_all(b"ping").unwrap();
    let mut request = [0; 4]; server.read_exact(&mut request).unwrap();
    server.write_all(b"pong").unwrap();
    let mut reply = [0; 4]; client.read_exact(&mut reply).unwrap();
    println!("TCP_OBSERVED request={} reply={}", std::str::from_utf8(&request).unwrap(), std::str::from_utf8(&reply).unwrap());
    assert_eq!(&request, b"ping");
    assert_eq!(std::str::from_utf8(&reply).unwrap(), want_reply, "TCP_REPLY_ASSERTION");
}
