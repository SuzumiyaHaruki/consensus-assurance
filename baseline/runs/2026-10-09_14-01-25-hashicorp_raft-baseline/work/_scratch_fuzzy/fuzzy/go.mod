// AUDIT SCRATCH COPY of fuzzy/go.mod: removed raft-boltdb/boltdb (unavailable
// offline) and pinned go-msgpack/v2 to the cached v2.1.2 so the repo's own fuzz
// harness can run against the audited module via the replace below.
module github.com/hashicorp/raft/fuzzy

go 1.20

require (
	github.com/hashicorp/go-hclog v1.6.2
	github.com/hashicorp/go-msgpack/v2 v2.1.2
	github.com/hashicorp/raft v1.2.0
)

require (
	github.com/armon/go-metrics v0.4.1 // indirect
	github.com/fatih/color v1.13.0 // indirect
	github.com/hashicorp/go-immutable-radix v1.0.0 // indirect
	github.com/hashicorp/go-metrics v0.5.4 // indirect
	github.com/hashicorp/golang-lru v0.5.0 // indirect
	github.com/mattn/go-colorable v0.1.12 // indirect
	github.com/mattn/go-isatty v0.0.14 // indirect
	golang.org/x/sys v0.13.0 // indirect
)

replace github.com/hashicorp/raft => ../..
