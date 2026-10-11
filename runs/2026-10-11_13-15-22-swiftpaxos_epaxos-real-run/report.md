# 共识审计研究报告

方法 `audit-products-v62`；模式 `real/autonomous`；持续 12.14 分钟。
停止原因：Agent stopped: Agent execution failed: This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via https://platform.openai.com/settings/organization/status-and-access before retrying.
This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. If you’re doing authorized security work that requires more cyber permissive safeguards, apply for Daybreak access via https://platform.openai.com/settings/organization/status-and-access before retrying.

## 问题与证据

### Does PrepareReply transport preserve the value ballot established by its producer and relied upon by recovery selection?

当前处置：调查中。
问题 `3b68c48182e94ac9a967a16fbe03ce7b-question-0` v1；来源：prepare_fields, prepare_codec, prepare_producer, prepare_consumer, send_wire, receive_wire（[完整引用](state.json)）。
假设：PrepareReply.Marshal and Unmarshal omit VBallot, causing replies with nonzero producer value ballots to arrive with zero and potentially altering recovery selection.
下一判别条件：Run actual proposal and prepare producers, observe emitted bytes and decoded fields for zero and nonzero initial value ballots, then investigate compatible histories in which this omission changes recovery selection.
问题边界：A local serialization mismatch does not by itself establish divergent decisions or FSM effects.

固定实验 `3b68c48182e94ac9a967a16fbe03ce7b-experiment` v1：[原始依据](fixed-experiments/3b68c48182e94ac9a967a16fbe03ce7b-experiment/basis.json)。
范围：Synchronous local protocol-producer and serialization probe in a three-replica configuration.
前史／供给条件：For each fresh case, handlePropose produces instance 0 at its original replica. Delay its outbound preaccepts. startRecoveryForInstance at replica 2 produces a Prepare, which is decoded and delivered to the original replica. handlePrepare constructs and serializes the reply through SendMsg. Decode into the fresh object used by the receive path and sample raw bytes, errors, all relevant fields and unconsumed bytes under single-threaded ownership.
假设：Empty handler state mirrors constructors, with small instance arrays and in-memory peer writers; network startup, UDP IP discovery, listeners, clocks and executor workers are omitted.；Thrifty mode, F=1, durable=false, no concurrency. Recovery invocation at an empty peer is supplied as a local handler stimulus; no timeout-based reachability or distributed consequence is claimed.
范围外：Distributed agreement violation；Client completion or FSM divergence；Crash restart and persistence
书面要求：A successful PrepareReply wire round trip must preserve the producer value ballot associated with its instance and prior phase; recovery compares that value ballot to select prior state.
执行 `6fe9f8ab79dd4690b3b8c6218de603a8`：completed，退出码 0；[回执](logs/6fe9f8ab79dd4690b3b8c6218de603a8/check.json)、[stdout](logs/6fe9f8ab79dd4690b3b8c6218de603a8/stdout.log)、[stderr](logs/6fe9f8ab79dd4690b3b8c6218de603a8/stderr.log)。
机械比较：violated；当前确认：未确认违反

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "case_id": "origin-0",
    "event": "prepare_admission",
    "instance": 0,
    "instance_replica": 0,
    "request": {
      "LeaderId": 2,
      "Replica": 0,
      "Instance": 0,
      "Ballot": 5
    },
    "request_ballot": 5,
    "source_replica": 0,
    "source_status": 1,
    "source_vballot": 0,
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]",
      "location": {
        "line": 4,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]"
      }
    }
  },
  {
    "case_id": "origin-0",
    "decode_error": "",
    "decoded": {
      "AcceptorId": 0,
      "Replica": 0,
      "Instance": 0,
      "Ballot": 5,
      "VBallot": 0,
      "Status": 1,
      "Command": [
        {
          "Op": 1,
          "K": 9,
          "V": "dmFsdWU="
        }
      ],
      "Seq": 0,
      "Deps": [
        -1,
        -1,
        -1
      ]
    },
    "decoded_vballot": 0,
    "event": "prepare_roundtrip",
    "instance": 0,
    "instance_replica": 0,
    "remaining_bytes": 0,
    "source_ballot": 5,
    "source_commands": [
      {
        "Op": 1,
        "K": 9,
        "V": "dmFsdWU="
      }
    ],
    "source_deps": [
      -1,
      -1,
      -1
    ],
    "source_replica": 0,
    "source_seq": 0,
    "source_status": 1,
    "source_vballot": 0,
    "wire_hex": "020000000000000000000000000500000001020109000000000000000500000076616c75650000000006ffffffffffffffffffffffff",
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]",
      "location": {
        "line": 5,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]"
      }
    }
  },
  {
    "case_id": "origin-1",
    "event": "prepare_admission",
    "instance": 0,
    "instance_replica": 1,
    "request": {
      "LeaderId": 2,
      "Replica": 1,
      "Instance": 0,
      "Ballot": 5
    },
    "request_ballot": 5,
    "source_replica": 1,
    "source_status": 1,
    "source_vballot": 1,
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]",
      "location": {
        "line": 6,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]"
      }
    }
  },
  {
    "case_id": "origin-1",
    "decode_error": "",
    "decoded": {
      "AcceptorId": 1,
      "Replica": 1,
      "Instance": 0,
      "Ballot": 5,
      "VBallot": 0,
      "Status": 1,
      "Command": [
        {
          "Op": 1,
          "K": 9,
          "V": "dmFsdWU="
        }
      ],
      "Seq": 0,
      "Deps": [
        -1,
        -1,
        -1
      ]
    },
    "decoded_vballot": 0,
    "event": "prepare_roundtrip",
    "instance": 0,
    "instance_replica": 1,
    "remaining_bytes": 0,
    "source_ballot": 5,
    "source_commands": [
      {
        "Op": 1,
        "K": 9,
        "V": "dmFsdWU="
      }
    ],
    "source_deps": [
      -1,
      -1,
      -1
    ],
    "source_replica": 1,
    "source_seq": 0,
    "source_status": 1,
    "source_vballot": 1,
    "wire_hex": "020100000001000000000000000500000001020109000000000000000500000076616c75650000000006ffffffffffffffffffffffff",
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]",
      "location": {
        "line": 7,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssurancePrepareValueBallotWire\"]"
      }
    }
  }
]
```
待解决：Current interpretation remains conditional, disputed or unresolved

归属解释历史：

- `d02596af8410432ea84a76fab33b8b79-interpretation-0` · 违反判断：CheckRun 6fe9f8ab79dd4690b3b8c6218de603a8 completed with exit 0. Comparison 0 has witness event 3 correlated to admission 2: producer value ballot 1 became decoded value ballot 0, with an empty decode error and zero remaining bytes. Events 0 and 1 are the same probe for producer value ballot 0 and match. Identity is the independently assigned case and source/instance tuple, not VBallot. Actual handlePropose creates the prior state, handlePrepare constructs the reply from inst.vbal, SendMsg calls the captured Marshal, and a fresh object decodes the resulting bytes as in replicaListener. The fixed codec contains no VBallot write or assignment. The applicable local responsibility is preservation of the prior value ballot needed by handlePrepareReply at lines 1239-1246; this conclusion does not require a chosen quorum. The reduced initialization omits runtime scheduling and capacity, neither of which changes this synchronous serializer endpoint.；依据来源 prepare_codec, prepare_producer, prepare_consumer, send_wire, receive_wire, proposal_prefix, epaxos_init, base_init，执行 6fe9f8ab79dd4690b3b8c6218de603a8。
  反证：The zero-ballot control retains its original value; the problem is masked when the producer value ballot equals the fresh object default.；Other sampled fields, including current ballot, status, commands, sequence and dependencies, are retained in these cases.
  限制：No recovery consumer selection, conflicting decision, FSM effect or client completion was executed in this probe.；The recovery invocation at an empty peer is supplied; no timeout-triggered distributed history is claimed.
### Does successful handleAccept retain enough phase status for a later recovery to distinguish accepted state from preaccepted or empty state?

当前处置：调查中。
问题 `3b68c48182e94ac9a967a16fbe03ce7b-question-1` v1；来源：accept_handler, prepare_producer, prepare_consumer（[完整引用](state.json)）。
假设：handleAccept updates ballots and attributes but appears not to set Status to ACCEPTED; prepare may consequently report a weaker phase.
下一判别条件：Produce Accept through an actual slow-path leader, deliver it to an acceptor, then issue Prepare and inspect the reported status; determine whether enclosing protections preserve chosen attributes.

固定实验 `d02596af8410432ea84a76fab33b8b79-experiment` v1：[原始依据](fixed-experiments/d02596af8410432ea84a76fab33b8b79-experiment/basis.json)。
范围：Five-replica, single-threaded, non-durable slow-path producer and local acceptor recovery-report probe.
前史／供给条件：Propose B at peer 1 and A at peer 0 on the same key. Deliver A preaccepts to peers 1 and 2 and their actual replies back to peer 0. Differing attributes cause the production slow transition and bcastAccept. Deliver those Accept messages, decode actual acknowledgments, sample acceptor status, and request Prepare using a fresh peer 3 recovery producer to inspect reported status.
假设：Empty initialization mirrors constructor state with bounded arrays and in-memory writers; production listeners, clocks and workers are omitted.；N=5, F=2, Thrifty=true. No instances, protocol messages or phase status are injected. Client proposals and a local recovery request are supplied at their interfaces.；The conflicting proposal at peer 1 remains in progress with its outbound traffic delayed.
范围外：Quorum decision preservation；FSM agreement；Timeout reachability；Crash restart
书面要求：An acceptor that handles a matching, non-stale Accept and emits its successful ballot acknowledgment must retain and report the accepted phase, so recovery can distinguish it from mere preacceptance.
执行 `9861dc25a45742c3a6c9fa2c637c86a1`：completed，退出码 0；[回执](logs/9861dc25a45742c3a6c9fa2c637c86a1/check.json)、[stdout](logs/9861dc25a45742c3a6c9fa2c637c86a1/stdout.log)、[stderr](logs/9861dc25a45742c3a6c9fa2c637c86a1/stderr.log)。
机械比较：violated；当前确认：未确认违反

实际观察（前 8 条，完整记录见原始输出）：

```json
[
  {
    "event": "delayed_conflicting_traffic",
    "from": 1,
    "wire_bytes_by_peer": {
      "2": "AwEAAAABAAAAAAAAAAEAAAACAQkAAAAAAAAAAQAAAEL/////Cv//////////////////////////",
      "3": "AwEAAAABAAAAAAAAAAEAAAACAQkAAAAAAAAAAQAAAEL/////Cv//////////////////////////"
    },
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
      "location": {
        "line": 4,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]"
      }
    }
  },
  {
    "event": "slow_prefix",
    "leader_before_status": 1,
    "peer": 1,
    "reply": {
      "Replica": 0,
      "Instance": 0,
      "Ballot": 0,
      "VBallot": 0,
      "Seq": 1,
      "Deps": [
        -1,
        0,
        -1,
        -1,
        -1
      ],
      "CommittedDeps": [
        -1,
        -1,
        -1,
        -1,
        -1
      ],
      "Status": 1
    },
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
      "location": {
        "line": 5,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]"
      }
    }
  },
  {
    "event": "slow_prefix",
    "leader_before_status": 1,
    "peer": 2,
    "reply": {
      "Replica": 0,
      "Instance": 0,
      "Ballot": 0,
      "VBallot": 0,
      "Seq": -1,
      "Deps": [
        -1,
        -1,
        -1,
        -1,
        -1
      ],
      "CommittedDeps": [
        -1,
        -1,
        -1,
        -1,
        -1
      ],
      "Status": 2
    },
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
      "location": {
        "line": 6,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]"
      }
    }
  },
  {
    "event": "slow_accept_produced",
    "leader_ballot": 0,
    "leader_deps": [
      -1,
      0,
      -1,
      -1,
      -1
    ],
    "leader_seq": 1,
    "leader_status": 3,
    "leader_vballot": 0,
    "slow_count": 1,
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
      "location": {
        "line": 7,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]"
      }
    }
  },
  {
    "accept": {
      "LeaderId": 0,
      "Replica": 0,
      "Instance": 0,
      "Ballot": 0,
      "Seq": 1,
      "Deps": [
        -1,
        0,
        -1,
        -1,
        -1
      ]
    },
    "acceptor": 1,
    "before_ballot": 0,
    "before_status": 1,
    "before_vballot": 0,
    "case_id": "acceptor-1",
    "event": "accept_admission",
    "instance": 0,
    "instance_replica": 0,
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
      "location": {
        "line": 8,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]"
      }
    }
  },
  {
    "accept_ballot": 0,
    "acceptor": 1,
    "ack_ballot": 0,
    "after_ballot": 0,
    "after_deps": [
      -1,
      0,
      -1,
      -1,
      -1
    ],
    "after_seq": 1,
    "after_status": 1,
    "after_vballot": 0,
    "case_id": "acceptor-1",
    "event": "accept_completion",
    "expected_accepted_status": 3,
    "instance": 0,
    "instance_replica": 0,
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
      "location": {
        "line": 9,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]"
      }
    }
  },
  {
    "acceptor": 1,
    "case_id": "acceptor-1",
    "event": "accepted_prepare_report",
    "expected_accepted_status": 3,
    "instance": 0,
    "instance_replica": 0,
    "prepare": {
      "LeaderId": 3,
      "Replica": 0,
      "Instance": 0,
      "Ballot": 8
    },
    "reply": {
      "AcceptorId": 1,
      "Replica": 0,
      "Instance": 0,
      "Ballot": 8,
      "VBallot": 0,
      "Status": 1,
      "Command": [
        {
          "Op": 1,
          "K": 9,
          "V": "QQ=="
        }
      ],
      "Seq": 1,
      "Deps": [
        -1,
        0,
        -1,
        -1,
        -1
      ]
    },
    "reported_status": 1,
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
      "location": {
        "line": 10,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]"
      }
    }
  },
  {
    "accept": {
      "LeaderId": 0,
      "Replica": 0,
      "Instance": 0,
      "Ballot": 0,
      "Seq": 1,
      "Deps": [
        -1,
        0,
        -1,
        -1,
        -1
      ]
    },
    "acceptor": 2,
    "before_ballot": 0,
    "before_status": 2,
    "before_vballot": 0,
    "case_id": "acceptor-2",
    "event": "accept_admission",
    "instance": 0,
    "instance_replica": 0,
    "_ca_stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
    "_ca_observation": {
      "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]",
      "location": {
        "line": 11,
        "stream": "[\"github.com/imdea-software/swiftpaxos/epaxos\",\"TestAssuranceAcceptRetainsPhase\"]"
      }
    }
  }
]
```
待解决：Execution has no attributed interpretation

## 共享理解与修订

- `d02596af8410432ea84a76fab33b8b79-knowledge-0` r1 · fact：PrepareReply.Marshal does not serialize VBallot and PrepareReply.Unmarshal does not assign it; a fresh receive object retains zero. In the retained actual-producer probe, initial value ballot 1 is decoded as 0 while initial value ballot 0 is unchanged.；条件：Successful decode into the fresh PrepareReply allocated by New; conclusions about protocol consequences require a compatible recovery history.。

## 执行成本与原始记录

Agent 调用 3 次；控制器目标执行 2 次。
目标进程累计秒数：16.381213；含准备的动作秒数：17.2257395609995；两者不相加。
请求模型：`gpt-6-astra` / `low`；服务端模型版本仅以回执为准。
[完整状态与历史](state.json)、[当前工作索引](research.json)、[实际配置](config.json)、[事件](events.jsonl)。
源码身份、工具成功及模型解释各有边界；脚本化产品仅验证框架，不作为自主发现证据。
