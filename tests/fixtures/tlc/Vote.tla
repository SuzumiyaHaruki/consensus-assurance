---------------------------- MODULE Vote ----------------------------
EXTENDS Naturals, FiniteSets
CONSTANTS NodeCount, MaxTerm, MaxCrashes, MessageBound, Broken
Candidates == 1..NodeCount
VARIABLES current, voteTerm, voteCand, phase, requestTerm, candidate, grants, crashes
vars == <<current, voteTerm, voteCand, phase, requestTerm, candidate, grants, crashes>>
Init == /\ current = 0 /\ voteTerm = 0 /\ voteCand = 0
        /\ phase = "idle" /\ requestTerm = 0 /\ candidate = 0
        /\ grants = {} /\ crashes = 0
Begin(t, c) == /\ phase = "idle" /\ MessageBound >= 1
               /\ requestTerm' = t /\ candidate' = c /\ phase' = "checkTerm"
               /\ UNCHANGED <<current, voteTerm, voteCand, grants, crashes>>
CheckTerm == /\ phase = "checkTerm"
             /\ IF requestTerm < current
                   THEN /\ phase' = "idle" /\ UNCHANGED current
                   ELSE /\ current' = requestTerm /\ phase' = "checkVote"
             /\ UNCHANGED <<voteTerm, voteCand, requestTerm, candidate, grants, crashes>>
CheckVote == /\ phase = "checkVote"
             /\ IF voteTerm = requestTerm /\ voteCand # 0
                   THEN /\ phase' = "idle"
                        /\ grants' = IF voteCand = candidate
                                      THEN grants \cup {<<requestTerm, candidate>>} ELSE grants
                   ELSE /\ phase' = "writeTerm" /\ UNCHANGED grants
             /\ UNCHANGED <<current, voteTerm, voteCand, requestTerm, candidate, crashes>>
WriteTerm == /\ phase = "writeTerm" /\ voteTerm' = requestTerm
             /\ phase' = "writeCandidate"
             /\ UNCHANGED <<current, voteCand, requestTerm, candidate, grants, crashes>>
WriteCandidate == /\ phase = "writeCandidate" /\ voteCand' = candidate
                  /\ phase' = "reply"
                  /\ UNCHANGED <<current, voteTerm, requestTerm, candidate, grants, crashes>>
Reply == /\ phase = "reply" /\ phase' = "idle"
         /\ grants' = grants \cup {<<requestTerm, candidate>>}
         /\ UNCHANGED <<current, voteTerm, voteCand, requestTerm, candidate, crashes>>
Abort == /\ phase \in {"checkTerm", "checkVote", "writeTerm", "writeCandidate"}
         /\ phase' = "idle"
         /\ UNCHANGED <<current, voteTerm, voteCand, requestTerm, candidate, grants, crashes>>
Crash == /\ phase # "down" /\ crashes < MaxCrashes
         /\ phase' = "down" /\ crashes' = crashes + 1
         /\ voteCand' = IF Broken THEN 0 ELSE voteCand
         /\ requestTerm' = 0 /\ candidate' = 0
         /\ UNCHANGED <<current, voteTerm, grants>>
Recover == /\ phase = "down" /\ phase' = "idle"
           /\ UNCHANGED <<current, voteTerm, voteCand, requestTerm, candidate, grants, crashes>>
Next == (\E t \in 1..MaxTerm, c \in Candidates: Begin(t,c))
        \/ CheckTerm \/ CheckVote \/ WriteTerm \/ WriteCandidate \/ Reply \/ Abort \/ Crash \/ Recover
VoteSafe == \A t \in 1..MaxTerm:
              Cardinality({c \in Candidates : <<t,c>> \in grants}) <= 1
Spec == Init /\ [][Next]_vars
=====================================================================
