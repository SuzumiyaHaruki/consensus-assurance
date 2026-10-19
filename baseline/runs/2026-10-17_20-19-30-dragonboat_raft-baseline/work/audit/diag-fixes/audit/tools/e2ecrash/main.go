package main

import (
	"encoding/binary"
	"fmt"
	"hash/crc32"
	"net"
	"os"
	"time"

	"github.com/lni/dragonboat/v3"
	"github.com/lni/dragonboat/v3/config"
)

func main() {
	dir, err := os.MkdirTemp("", "e2ecrash")
	if err != nil {
		panic(err)
	}
	defer os.RemoveAll(dir)
	addr := "127.0.0.1:26999"
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
	payload := []byte{
		0x0A, 0x00,
		0x0A,
		0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x01,
	}
	conn, err := net.Dial("tcp", addr)
	if err != nil {
		panic(err)
	}
	magic := []byte{0xAE, 0x7D}
	hdr := make([]byte, 18)
	binary.BigEndian.PutUint16(hdr, 100) // raftType
	binary.BigEndian.PutUint64(hdr[2:], uint64(len(payload)))
	binary.BigEndian.PutUint32(hdr[14:], crc32.ChecksumIEEE(payload))
	binary.BigEndian.PutUint32(hdr[10:], 0)
	binary.BigEndian.PutUint32(hdr[10:], crc32.ChecksumIEEE(hdr))
	if _, err := conn.Write(magic); err != nil {
		panic(err)
	}
	if _, err := conn.Write(hdr); err != nil {
		panic(err)
	}
	if _, err := conn.Write(payload); err != nil {
		panic(err)
	}
	time.Sleep(2 * time.Second)
	fmt.Println("NODEHOST SURVIVED THE MALFORMED BATCH")
}
