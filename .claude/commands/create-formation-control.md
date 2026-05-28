Create a new Formation Control implementation for the following domain: $ARGUMENTS

Follow the Formation Control pattern exactly:

**Step 1 — Define Vec2 and Obstacle dataclasses**
- `Vec2`: x, y floats with `__add__`, `__sub__`, `__mul__`, `__rmul__`, `norm()`, `normalized()`, `clamp(max_n)`, `__repr__`
- `Obstacle`: center (Vec2), radius (float), label (str="OBS")

**Step 2 — Define AgentUnit (or domain-specific name) dataclass**
- Fields: agent_id, pos (Vec2), offset (Vec2), neighbor_id (Optional[str]), is_leader=False, vel (Vec2), status="NOMINAL"
- Control parameters: KP=0.50, MAX_SPEED=3.00, TOLERANCE=0.40, AVOIDANCE_K=14.0, AVOIDANCE_DIST=5.0
- `update(neighbor_pos, obstacles) → str`:
  1. Compute `desired = neighbor_pos + offset`
  2. `error = desired - pos`, `velocity = (error * KP).clamp(MAX_SPEED)`
  3. Obstacle repulsion: for each obstacle within `radius + AVOIDANCE_DIST`, add `to_me.normalized() * AVOIDANCE_K * (1 - dist/threshold)` to repulsion
  4. `vel = (velocity + repulsion).clamp(MAX_SPEED * 1.8)`, `pos += vel`
  5. Return status tag: "AVOID" if repulsion active, "REFORM" if just recovered, "HOLD" if within TOLERANCE, "ADJUST" otherwise

**Step 3 — Build SwarmFormation (observer + printer only)**
- `__init__(agents, obstacles=None, name)`: builds `by_id` dict, finds leader
- `step(leader_move) → List[(agent_id, tag)]`: moves leader by `leader_move`, calls `agent.update()` for all followers
- `run(trajectory, print_interval=5, always_print_events=False)`: drives leader through trajectory
- `formation_error() → float`: average distance from desired position across all followers
- `max_deviation() → float`: worst single-agent deviation
- `_print_snapshot(label)`: ASCII W=54, H=14 grid; agents as digits; obstacles as `#`; empty as `·`
- `_print_tick(events)`: per-agent status with icons ⚠ AVOID, ✅ REFORM, 🔄 ADJUST
- `_print_metrics()`: ticks, final error, max deviation, error convergence bar chart

**Step 4 — Neighbor graph patterns**

Use one of these patterns (or combine) for the domain:
```
Line (chain):  A0→A1→A2→A3          offset=(+spacing, 0) — side-by-side
Column:        A0→A1→A2→A3          offset=(0, -spacing) — follow-the-leader
V-shape:       A0→A1, A0→A2;        offset=(±wing_x, -wing_y)
               A1→A3, A2→A4
Grid (2×N):    Row0 chain + Row1 each follows directly above + row offset
Diamond:       A0→A1,A2; A1,A2→A3  diagonal offsets
```

**Step 5 — Four demos**
- Demo 1: Simple forward march with the base formation
- Demo 2: Alternative formation shape (V, diamond, or grid)
- Demo 3: Obstacle avoidance — place obstacle to the SIDE of a middle agent's path (not head-on, for dramatic lateral dodge); show AVOID cascade and REFORM
- Demo 4: Formation through a direction change (turn) — 3 phases: forward + diagonal + perpendicular

**Steady-state lag guideline:**
Each follower lags `leader_speed / KP` units from its neighbor in the travel direction. With KP=0.5 and speed=1.5: lag = 3 units per hop. For tight formations, use lower leader speed or higher KP (oscillation risk above KP≈0.8).

**Obstacle placement for Demo 3:**
Obstacle should be to the right or left of the target agent's path, not directly in front. This produces a dramatic x-deviation (lateral avoidance) that clearly shows in the ASCII snapshot and error spike. Obstacle to the RIGHT of drone at x=24 → place at (x+5, y_ahead) → repulsion pushes drone LEFT.

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/formation_control_<domain>.py
