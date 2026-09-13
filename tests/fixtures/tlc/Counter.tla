---------------------------- MODULE Counter ----------------------------
EXTENDS Naturals
CONSTANTS Limit, Broken
VARIABLE value
Init == value = 0
Next == \/ /\ value < Limit /\ value' = value + 1
        \/ /\ value = Limit /\ value' = IF Broken THEN value + 1 ELSE 0
WithinCapacity == value <= Limit
Spec == Init /\ [][Next]_value
========================================================================
