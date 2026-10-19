package org.apache.zookeeper.server.quorum;

import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.txn.TxnHeader;

/**
 * syncWithLeader starts lastQueued at 0; enforceContinuousProposal therefore
 * accepts a first proposal at any higher zxid without checking the actual
 * synchronization position.
 */
public class SyncFirstGapRepro {
    public static void main(String[] args) throws Exception {
        Learner learner = new Learner();
        Learner.PacketInFlight pif = new Learner.PacketInFlight();
        pif.hdr = new TxnHeader(1, 0, 5L, 5L, ZooDefs.OpCode.create);

        long returned = learner.enforceContinuousProposal(0L, pif);
        System.out.println("enforceContinuousProposal returned: " + returned);
        throw new AssertionError(
            "first sync proposal at zxid 5 was accepted with no predecessor");
    }
}
