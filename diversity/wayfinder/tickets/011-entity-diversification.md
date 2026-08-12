---
id: 011
title: Entity-name diversification
type: grilling
mode: HITL
status: closed
assignee: claude + user (HITL, 2026-08-09)
resolved: 2026-08-09
blocked-by: [004]
---

## Question

The audit found name convergence ("Priya" 6/26, "Marcus" 3/26, "Halloway" 3×). Where do we break it? Options: (a) a name/entity pool or ban-list in the seed spec (seed side, does not touch the frozen generator prompt); (b) a post-hoc rejection rule in the gate (reject the Nth reuse); (c) accept and disclose. Constraint: the generator prompt is frozen.

## Resolution (user, 2026-08-09)

Option (a): entity names move into the seed spec, drawn from a pool without replacement per batch. The generator prompt stays frozen.
