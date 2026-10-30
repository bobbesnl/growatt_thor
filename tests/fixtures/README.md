# Contract fixture provenance

`sensor_contracts.json` was rechecked against the sensor implementation at `b87d002^`, before the description-table refactor. All 140 projections match, including unrecorded attributes and resolved native units. The active-power threshold retains its original integer type; the test checks that type separately because JSON number equality alone does not distinguish it.

`control_write_contracts.json` was rechecked against the platform entities and configuration mixin at `5da0116^`, before the write-hook refactor. All 84 projections match, including WarmUp, AuthorizationMode and both directions of the three switches. The comparison exercises the same production queue with each implementation and compares notifications, reported configuration, errors and final state. These are behavioral snapshots; they do not prove compatibility with every Home Assistant implementation detail.
