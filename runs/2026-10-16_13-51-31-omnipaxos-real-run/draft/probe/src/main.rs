fn main(){ let (s,r)=async_channel::bounded::<u8>(1); s.try_send(1).unwrap(); println!("{:?}", r.try_recv()); }
