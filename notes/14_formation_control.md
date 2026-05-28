# Formation Control
## Decentralized Swarm Coordination via Local Neighbor Rules

---

## What Problem Does This Solve?

Coordinating a group of agents to move as a coherent physical unit — a drone swarm spraying a field, a robot squad clearing terrain, a fleet of autonomous vehicles maintaining safe spacing — requires every agent to know where to go relative to its peers.

The naive solution is a central controller that computes and commands each agent's exact position every tick. This approach breaks down at scale:
- A single controller is a bottleneck and single point of failure
- Communication bandwidth grows with swarm size
- The controller must know every agent's state at all times
- When one agent fails, the controller must recompute the entire plan

Formation Control solves this by pushing the decision logic into each agent. Every agent obeys one simple rule: **maintain a fixed offset from your designated neighbor**. No global plan. No central commands. The collective shape emerges from local sensing alone.

---

## The Core Control Loop

Every agent runs the same five-step loop at each simulation tick:

```
1. SENSE   — read neighbor's current position
2. DESIRE  — desired_pos = neighbor.pos + fixed_offset
3. ERROR   — error = desired_pos - current_pos
4. CORRECT — velocity = KP × error + obstacle_repulsion (clamped to MAX_SPEED)
5. REPORT  — update position, return status tag
```

In code:
```python
desired  = neighbor_pos + self.offset
error    = desired - self.pos
velocity = (error * self.KP).clamp(self.MAX_SPEED)
# ... add obstacle repulsion ...
self.vel = (velocity + repulsion).clamp(self.MAX_SPEED * 1.8)
self.pos = self.pos + self.vel
```

This is a **proportional controller** — the simplest member of the PID family. The velocity is proportional to the position error. The formation is never perfectly rigid (there is always a small steady-state lag during motion), but it is stable and self-correcting.

---

## The Neighbor Graph

The formation shape is entirely determined by two things:
1. **The neighbor graph** — who follows whom
2. **The offset** — how far and in what direction

Different graphs produce different formations:

| Formation | Graph | Offset |
|---|---|---|
| Line (side-by-side) | A0→A1→A2→A3 chain | (+spacing, 0) |
| Column (follow-leader) | A0→A1→A2→A3 chain | (0, -spacing) |
| V-shape | A0→L1, A0→R1; L1→L2, R1→R2 | (±wing_x, -wing_y) |
| 2×3 Grid | Row0 chain; each Row1 follows above + row offset | Front: (+spacing, 0); Back: (0, -row_spacing) |

Changing the formation means **only changing the neighbor graph and offsets** — the control loop is identical for every agent in every formation.

---

## Steady-State Lag

A pure proportional controller introduces a **steady-state lag** during motion:

```
lag_per_hop = leader_speed / KP
```

Example: `leader_speed=1.5, KP=0.5` → `lag = 3.0 units` per hop in the direction of travel.

In a 4-drone chain, the last drone (3 hops from the leader) lags 9 units behind in y when the formation is moving at steady speed. This is acceptable for most applications and actually realistic — it mirrors how real convoys behave.

**Tuning KP:**
- **Higher KP** (e.g., 0.8): tighter tracking, less lag, but oscillation risk above ~0.9
- **Lower KP** (e.g., 0.3): smoother motion, more lag, slower reformation after disturbance
- **Rule of thumb**: keep `KP × tick_duration < 1` to avoid overshooting

---

## Obstacle Avoidance

Each agent runs an obstacle repulsion sub-loop in parallel with the formation control:

```python
for obs in obstacles:
    to_me     = self.pos - obs.center      # vector pointing away from obstacle
    dist      = to_me.norm()
    threshold = obs.radius + AVOIDANCE_DIST
    if dist < threshold:
        strength  = AVOIDANCE_K * (1.0 - dist / threshold)
        repulsion += to_me.normalized() * strength
```

The repulsion strength is zero at the detection boundary and maximum at the obstacle surface. This creates a smooth "force field" effect — agents slow their approach and curve around obstacles.

**Cascade effect**: when Drone-2 detects an obstacle and deviates, its position changes. Drone-3 (whose neighbor is Drone-2) senses this change and adjusts. Drone-4 senses Drone-3's adjustment. The disturbance propagates through the chain — exactly the emergent collective behavior described in the book:

```
Drone-2 detects tree → AVOIDING → deviates in x
  → Drone-3 also detects tree (within its own AVOIDANCE_DIST) → AVOIDING
  → Drone-2 clears tree → REFORMING → drifts back to x offset
  → Drone-3 also clears → REFORMING → drifts back
```

**Placement matters**: for visually dramatic avoidance, place the obstacle **to the side** of the drone's path. A drone approaching a head-on obstacle is simply pushed backward (slows down). A drone approaching an obstacle offset in x gets pushed sideways — a much more visible deviation.

---

## Formation Error Metric

Formation quality is measured by the **average distance from desired position**:

```python
def formation_error(self) -> float:
    errs = []
    for a in followers:
        desired = a.neighbor.pos + a.offset
        errs.append((desired - a.pos).norm())
    return mean(errs)
```

Typical values:
- **0.0**: perfect formation (static or perfectly synchronized)
- **< 1.0**: tight formation under motion (normal operational range)
- **1–5**: formation slightly stretched by lag or obstacle avoidance
- **> 5**: formation breaking apart — tuning needed or obstacle too close

---

## Status Machine

Each follower transitions through these states:

```
NOMINAL    ←→ ADJUSTING     (normal: within tolerance ↔ correcting lag)
NOMINAL/ADJUSTING → AVOIDING    (obstacle detected within threshold)
AVOIDING → REFORMING    (obstacle cleared, drifting back to position)
REFORMING → NOMINAL     (error < TOLERANCE again)
```

Status is reported every tick so the observer can track the cascade.

---

## Formation Types Demonstrated

### Line Formation (Demo 1)
```
   0─────1─────2─────3   (moving upward ↑)
   offset: (+12, 0) per hop
```
Agents maintain x-spacing. Y-lag creates a slight staircase during motion.

### V-Formation (Demo 2)
```
           0             (Apex, leader)
        1     2          (Wing-L1, Wing-R1, offsets ±10 back-diagonal)
     3           4       (Wing-L2, Wing-R2, further back-diagonal)
```
Each wing tier follows the one above it. The V opens toward the rear.

### Obstacle Avoidance (Demo 3)
```
   0─────1─────2──#──3   (obstacle to right of Drone-2 at y≈14)
         ↑     ←          (Drone-2 pushed left; Drone-3 follows)
```

### Grid Formation with Turn (Demo 4)
```
   0─────1─────2   (Row 0)
   │     │     │
   3─────4─────5   (Row 1)
   
   → Forward 15 ticks → 45° pivot 8 ticks → Right 12 ticks
```

---

## Comparison with Other Coordination Patterns

| Dimension | Formation Control | Swarm Architecture | Resource Allocation |
|---|---|---|---|
| Decision locus | Each agent (local) | Each agent (local) | Central dispatcher |
| Communication | Neighbor position only | Shared task board | Submit/receive only |
| Output | Continuous positions | Task completion | Slot assignment |
| Failure mode | Lag / oscillation | Missed tasks | Starvation / preemption |
| Real-world analog | Drone swarms | Self-organizing teams | Scheduler |

Formation Control is the spatial/physical version of Swarm Architecture: both are decentralized and emergent, but Formation Control operates on continuous positions rather than discrete tasks.

---

## Pros and Cons

### Pros
- **Scalability**: adding a drone adds one edge to the neighbor graph — no central computation increases
- **Resilience**: if a drone fails, its successor's neighbor is gone; the gap closes naturally
- **Simplicity**: each agent's entire program fits in 10 lines of code
- **No communication overhead**: each agent only needs its one neighbor's position

### Cons
- **Lag**: proportional controllers introduce steady-state position error during motion — the formation is never perfectly rigid while moving
- **Local optima**: agents navigating by local rules can get trapped in a cul-de-sac that a global planner would avoid
- **Oscillation risk**: high KP values can cause agents to overshoot and oscillate around their target positions
- **Chain vulnerability**: in a long chain formation, a failure near the front propagates backward — the rear of the formation has no direct knowledge of the leader's position

---

## When to Use

✅ Use when:
- Agents must maintain a physical or logical spatial structure (robotics, drones, simulations)
- The environment requires dynamic adaptation (obstacles, terrain, varying density)
- Scalability to hundreds or thousands of agents is needed
- Central coordination would be a bottleneck or single point of failure

❌ Avoid when:
- Exact global positioning is required (use centralized path planner)
- Agents have no ability to sense their neighbor's position
- The formation must be globally optimal (greedy local rules are not optimal)

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `formation_control.py` | Line, V, obstacle avoidance, and grid-with-turn demos; ASCII snapshots; error convergence bars |

---

## Real-World Equivalents

- **Agricultural drone swarms**: multi-rotor drones spray fields in a precise grid — each drone maintains offset from its neighbor to ensure even chemical coverage
- **Military UAV formation**: fighter drones maintain V-formation for sensor coverage and electronic warfare; human pilots in real aircraft use the same formation rules
- **Autonomous vehicle platoons**: trucks on a highway maintain fixed headway from the vehicle ahead; a speed change cascades through the platoon
- **Search-and-rescue robot squads**: ground robots sweep terrain in a line formation, each maintaining spacing from the adjacent robot
- **Fish schooling / bird flocking**: natural systems using identical principles — each animal follows a few neighbors with simple rules; the entire flock/school acts as a single fluid entity
- **Satellite constellations**: satellites in low-Earth orbit maintain relative positions using small thruster corrections — exactly the proportional controller pattern
