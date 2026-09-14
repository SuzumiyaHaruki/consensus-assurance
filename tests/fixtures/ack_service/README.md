# Synthetic acknowledgement contracts
The memory configuration promises acceptance before response, not durable storage.
The durable configuration promises successful durable completion before response.
An early response in durable configuration violates that promise even if intentional.
The conflict configuration has unresolved contradictory memory and durability promises.
This is a controlled fixture, not a MongoDB or Hashicorp implementation or finding.
