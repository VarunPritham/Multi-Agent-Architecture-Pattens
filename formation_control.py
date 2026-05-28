"""
Formation Control — Pattern 14
Decentralized swarm coordination via local neighbor rules.

Each agent knows only one thing: maintain a fixed offset from its designated neighbor.
No central planner. Collective shape emerges from local sensing alone.

Demos:
  1. Line formation       — 4 drones march side-by-side, 25 ticks
  2. V-formation          — 5 drones in aerodynamic V, search-and-rescue sweep
  3. Obstacle avoidance   — center drone detects tree, deviates, formation reforms
  4. Grid formation       — 6 drones in 2×3 grid, sweeps forward then turns 90°
"""

from __future__ import annotations
import os, math
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple

USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))   # not needed — pure physics sim

# ── Vec2 ───────────────────────────────────────────────────────────────────────

@dataclass
class Vec2:
    x: float = 0.0
    y: float = 0.0

    def __add__(self, o: "Vec2")  -> "Vec2": return Vec2(self.x + o.x, self.y + o.y)
    def __sub__(self, o: "Vec2")  -> "Vec2": return Vec2(self.x - o.x, self.y - o.y)
    def __mul__(self, s: float)   -> "Vec2": return Vec2(self.x * s,   self.y * s)
    def __rmul__(self, s: float)  -> "Vec2": return self.__mul__(s)

    def norm(self) -> float:
        return math.hypot(self.x, self.y)

    def normalized(self) -> "Vec2":
        n = self.norm()
        return Vec2(self.x / n, self.y / n) if n > 1e-9 else Vec2(0.0, 0.0)

    def clamp(self, max_n: float) -> "Vec2":
        n = self.norm()
        return Vec2(self.x * max_n / n, self.y * max_n / n) if n > max_n else Vec2(self.x, self.y)

    def __repr__(self) -> str:
        return f"({self.x:+6.1f},{self.y:+6.1f})"


# ── Obstacle ───────────────────────────────────────────────────────────────────

@dataclass
class Obstacle:
    center: Vec2
    radius: float
    label:  str = "OBS"


# ── DroneAgent ─────────────────────────────────────────────────────────────────

@dataclass
class DroneAgent:
    """
    Implements the Formation Control core loop:

      1. Sense  — read neighbor's current position
      2. Desire — compute desired position = neighbor.pos + offset
      3. Error  — desired - current
      4. Correct— apply proportional velocity + obstacle repulsion
      5. Report — return event tag (HOLD / ADJUST / AVOID / REFORM)
    """
    drone_id:    str
    pos:         Vec2
    offset:      Vec2 = field(default_factory=Vec2)   # fixed offset relative to neighbor
    neighbor_id: Optional[str] = None
    is_leader:   bool = False
    vel:         Vec2 = field(default_factory=Vec2)
    status:      str  = "NOMINAL"

    # ── Control law parameters ────────────────────────────────────────────────
    KP:             float = 0.50   # proportional gain (higher → tighter, oscillation risk)
    MAX_SPEED:      float = 3.00   # max follower speed (units/tick)
    TOLERANCE:      float = 0.40   # formation error below this → NOMINAL
    AVOIDANCE_K:    float = 14.0   # repulsion magnitude
    AVOIDANCE_DIST: float = 5.0    # detection zone beyond obstacle radius

    def update(self, neighbor_pos: Vec2, obstacles: List[Obstacle]) -> str:
        if self.is_leader:
            return "LEADER"

        # ── 1–3. Sense → Desire → Error ───────────────────────────────────────
        desired  = neighbor_pos + self.offset
        error    = desired - self.pos
        err_norm = error.norm()

        # ── 4a. Proportional heading ──────────────────────────────────────────
        velocity = (error * self.KP).clamp(self.MAX_SPEED)

        # ── 4b. Obstacle repulsion ────────────────────────────────────────────
        repulsion = Vec2(0.0, 0.0)
        for obs in obstacles:
            to_me     = self.pos - obs.center
            dist      = to_me.norm()
            threshold = obs.radius + self.AVOIDANCE_DIST
            if dist < threshold and dist > 1e-9:
                strength  = self.AVOIDANCE_K * (1.0 - dist / threshold)
                repulsion = repulsion + to_me.normalized() * strength

        # ── 4c. Composite velocity + integrate position ───────────────────────
        self.vel = (velocity + repulsion).clamp(self.MAX_SPEED * 1.8)
        self.pos = self.pos + self.vel

        # ── 5. Status tag ─────────────────────────────────────────────────────
        if repulsion.norm() > 0.1:
            self.status = "AVOIDING"
            return "AVOID"
        elif err_norm < self.TOLERANCE:
            if self.status in ("AVOIDING", "REFORMING"):
                self.status = "NOMINAL"
                return "REFORM"          # just rejoined formation
            self.status = "NOMINAL"
            return "HOLD"
        else:
            if self.status == "AVOIDING":
                self.status = "REFORMING"
            elif self.status != "REFORMING":
                self.status = "ADJUSTING"
            return "ADJUST"


# ── SwarmFormation ─────────────────────────────────────────────────────────────

class SwarmFormation:
    """
    Orchestrates the tick loop and output.
    Not a central controller — only an observer and printer.
    All movement decisions are made locally inside each DroneAgent.
    """

    def __init__(self, agents: List[DroneAgent],
                 obstacles: List[Obstacle] = None,
                 name: str = "Swarm"):
        self.name      = name
        self.agents    = agents
        self.by_id:    Dict[str, DroneAgent] = {a.drone_id: a for a in agents}
        self.leader    = next(a for a in agents if a.is_leader)
        self.obstacles = obstacles or []
        self.tick      = 0
        self._err_log: List[float] = []

    # ── Simulation ─────────────────────────────────────────────────────────────

    def step(self, leader_move: Vec2) -> List[Tuple[str, str]]:
        """Advance one tick. Returns list of (drone_id, event_tag)."""
        self.tick += 1
        self.leader.pos = self.leader.pos + leader_move
        self.leader.vel = leader_move

        events: List[Tuple[str, str]] = []
        for a in self.agents:
            if a.is_leader:
                continue
            nb  = self.by_id.get(a.neighbor_id)
            tag = a.update(nb.pos if nb else a.pos, self.obstacles)
            events.append((a.drone_id, tag))

        self._err_log.append(self.formation_error())
        return events

    def run(self, trajectory: List[Vec2],
            print_interval: int = 5,
            always_print_events: bool = False) -> None:
        """Drive the leader along trajectory; print every print_interval ticks."""
        print(f"  Initial formation error: {self.formation_error():.2f} units")
        self._print_snapshot("t=0  (before)")
        for i, move in enumerate(trajectory):
            events = self.step(move)
            notable = any(tag in ("AVOID", "REFORM") for _, tag in events)
            if (i + 1) % print_interval == 0 or (always_print_events and notable):
                self._print_tick(events)
        self._print_snapshot(f"t={self.tick}  (after)")
        self._print_metrics()

    # ── Metrics ────────────────────────────────────────────────────────────────

    def formation_error(self) -> float:
        """Average distance from desired position across all followers."""
        errs = []
        for a in self.agents:
            if a.is_leader:
                continue
            nb = self.by_id.get(a.neighbor_id)
            if nb:
                errs.append((nb.pos + a.offset - a.pos).norm())
        return sum(errs) / len(errs) if errs else 0.0

    def max_deviation(self) -> float:
        """Maximum single-agent distance from desired position."""
        devs = []
        for a in self.agents:
            if a.is_leader:
                continue
            nb = self.by_id.get(a.neighbor_id)
            if nb:
                devs.append((nb.pos + a.offset - a.pos).norm())
        return max(devs, default=0.0)

    # ── Print helpers ───────────────────────────────────────────────────────────

    def _print_tick(self, events: List[Tuple[str, str]]):
        icons = {"AVOID": "⚠ ", "REFORM": "✅", "ADJUST": "🔄", "HOLD": "  "}
        err   = self.formation_error()
        print(f"\n  ── Tick {self.tick:3d}  avg_err={err:5.2f} ──────────────────────")
        print(f"     {'Leader':12s}  pos={self.leader.pos}")
        for drone_id, tag in events:
            a    = self.by_id[drone_id]
            nb   = self.by_id.get(a.neighbor_id)
            dev  = (nb.pos + a.offset - a.pos).norm() if nb else 0.0
            icon = icons.get(tag, "  ")
            print(f"  {icon} {drone_id:12s}  pos={a.pos}  dev={dev:4.1f}  [{a.status}]")

    def _print_snapshot(self, label: str):
        """ASCII top-down view. Agents shown as numbers, obstacles as ###."""
        all_x = [a.pos.x for a in self.agents] + [o.center.x for o in self.obstacles]
        all_y = [a.pos.y for a in self.agents] + [o.center.y for o in self.obstacles]
        x_min = min(all_x) - 6;  x_max = max(all_x) + 9
        y_min = min(all_y) - 4;  y_max = max(all_y) + 7
        W, H = 54, 14

        def cell(x: float, y: float) -> Tuple[int, int]:
            c = int((x - x_min) / max(x_max - x_min, 1) * (W - 1))
            r = H - 1 - int((y - y_min) / max(y_max - y_min, 1) * (H - 1))
            return max(0, min(W - 1, c)), max(0, min(H - 1, r))

        grid = [['·'] * W for _ in range(H)]

        for obs in self.obstacles:
            cx, cy = cell(obs.center.x, obs.center.y)
            for dr in range(-1, 2):
                for dc in range(-2, 3):
                    rr, cc = cy + dr, cx + dc
                    if 0 <= rr < H and 0 <= cc < W:
                        grid[rr][cc] = '#'

        for i, a in enumerate(self.agents):
            c, r = cell(a.pos.x, a.pos.y)
            grid[r][c] = str(i) if i < 10 else chr(ord('A') + i - 10)

        print(f"\n  {label}")
        print(f"  ┌{'─' * W}┐")
        for row in grid:
            print(f"  │{''.join(row)}│")
        print(f"  └{'─' * W}┘")
        parts = []
        for i, a in enumerate(self.agents):
            ch  = str(i) if i < 10 else chr(ord('A') + i - 10)
            tag = "★" if a.is_leader else ""
            parts.append(f"{ch}={a.drone_id}{tag}({a.pos.x:.0f},{a.pos.y:.0f})")
        for j in range(0, len(parts), 3):
            print("  " + "  ".join(parts[j:j + 3]))

    def _print_metrics(self):
        print(f"\n  ══ Formation Metrics ════════════════════════════════")
        print(f"     Ticks run       : {self.tick}")
        print(f"     Final avg error : {self.formation_error():.3f} units")
        print(f"     Final max dev   : {self.max_deviation():.3f} units")
        if self._err_log:
            peak    = max(self._err_log)
            buckets = min(8, len(self._err_log))
            step    = max(1, len(self._err_log) // buckets)
            samples = self._err_log[::step][:buckets]
            print(f"\n  Error over time (peak={peak:.2f}):")
            for j, e in enumerate(samples):
                bar = '█' * min(30, int(e / peak * 30)) if peak > 0 else ''
                print(f"    t≈{j * step + 1:3d}  {bar:<30s} {e:.2f}")
        print(f"\n  {'Agent':14s}  {'Final pos':14s}  {'Dev':>6s}  Status")
        print(f"  {'─'*14}  {'─'*14}  {'─'*6}  {'─'*10}")
        for a in self.agents:
            nb  = self.by_id.get(a.neighbor_id)
            dev = (nb.pos + a.offset - a.pos).norm() if nb and not a.is_leader else 0.0
            dv  = "★ leader" if a.is_leader else f"{dev:6.2f}"
            print(f"  {a.drone_id:14s}  {str(a.pos):14s}  {dv:>6s}  {a.status}")
        print()


# ── Demo helpers ───────────────────────────────────────────────────────────────

def _hdr(title: str, subtitle: str = ""):
    print("\n" + "═" * 66)
    print(f"  {title}")
    print("═" * 66)
    if subtitle:
        print(f"  {subtitle}\n")


# ══ DEMO 1 — Line Formation ════════════════════════════════════════════════════

def demo1_line_formation():
    _hdr(
        "DEMO 1 — Line Formation: Agricultural Drone Sweep",
        "4 drones in a side-by-side line (offset +12 in x).\n"
        "  Leader marches forward (+y). Followers maintain x-spacing."
    )
    agents = [
        DroneAgent("Drone-0", Vec2( 0, 0), is_leader=True),
        DroneAgent("Drone-1", Vec2(12, 0), offset=Vec2(12, 0), neighbor_id="Drone-0"),
        DroneAgent("Drone-2", Vec2(24, 0), offset=Vec2(12, 0), neighbor_id="Drone-1"),
        DroneAgent("Drone-3", Vec2(36, 0), offset=Vec2(12, 0), neighbor_id="Drone-2"),
    ]
    swarm = SwarmFormation(agents, name="LineSweep")
    swarm.run([Vec2(0, 1.5)] * 25, print_interval=5)


# ══ DEMO 2 — V-Formation ══════════════════════════════════════════════════════

def demo2_v_formation():
    _hdr(
        "DEMO 2 — V-Formation: Search & Rescue Sweep",
        "5 drones in a V. Apex leads; wings sit (-10, ±9) behind per tier.\n"
        "  V-shape maintained as formation sweeps forward."
    )
    agents = [
        DroneAgent("Apex",    Vec2(20,  0), is_leader=True),
        DroneAgent("Wing-L1", Vec2(10, -9), offset=Vec2(-10, -9), neighbor_id="Apex"),
        DroneAgent("Wing-R1", Vec2(30, -9), offset=Vec2( 10, -9), neighbor_id="Apex"),
        DroneAgent("Wing-L2", Vec2( 0,-18), offset=Vec2(-10, -9), neighbor_id="Wing-L1"),
        DroneAgent("Wing-R2", Vec2(40,-18), offset=Vec2( 10, -9), neighbor_id="Wing-R1"),
    ]
    swarm = SwarmFormation(agents, name="V-Search")
    swarm.run([Vec2(0, 1.5)] * 25, print_interval=5)


# ══ DEMO 3 — Obstacle Avoidance ═══════════════════════════════════════════════

def demo3_obstacle_avoidance():
    _hdr(
        "DEMO 3 — Obstacle Avoidance: Drone-2 Detects Tree",
        "Line of 4. Obstacle placed to the right of Drone-2's path at y≈14.\n"
        "  Drone-2 deflects left. Drone-3 follows. Formation self-reforms."
    )
    agents = [
        DroneAgent("Drone-0", Vec2( 0, 0), is_leader=True),
        DroneAgent("Drone-1", Vec2(12, 0), offset=Vec2(12, 0), neighbor_id="Drone-0"),
        DroneAgent("Drone-2", Vec2(24, 0), offset=Vec2(12, 0), neighbor_id="Drone-1"),
        DroneAgent("Drone-3", Vec2(36, 0), offset=Vec2(12, 0), neighbor_id="Drone-2"),
    ]
    # Obstacle to the RIGHT of Drone-2 (x=24) at (29, 14):
    # repulsion pushes Drone-2 in the -x direction (left), away from obstacle.
    obstacles = [Obstacle(center=Vec2(29, 14), radius=3.0, label="TREE")]
    swarm = SwarmFormation(agents, obstacles=obstacles, name="ObstacleTest")
    swarm.run([Vec2(0, 1.0)] * 35, print_interval=5, always_print_events=True)


# ══ DEMO 4 — Grid Formation with Turn ════════════════════════════════════════

def demo4_grid_with_turn():
    _hdr(
        "DEMO 4 — Grid Formation: 2×3 Grid Sweeps Then Turns 90°",
        "6 drones in 2 rows × 3 columns. Marches +y for 15 ticks,\n"
        "  then pivots 45° for 8 ticks, then marches +x for 12 ticks."
    )
    # Row 0 (front): Drone-0 Drone-1 Drone-2
    # Row 1 (rear) : Drone-3 Drone-4 Drone-5
    agents = [
        DroneAgent("Drone-0", Vec2( 0,  0), is_leader=True),
        DroneAgent("Drone-1", Vec2(12,  0), offset=Vec2(12,  0), neighbor_id="Drone-0"),
        DroneAgent("Drone-2", Vec2(24,  0), offset=Vec2(12,  0), neighbor_id="Drone-1"),
        DroneAgent("Drone-3", Vec2( 0,-12), offset=Vec2( 0,-12), neighbor_id="Drone-0"),
        DroneAgent("Drone-4", Vec2(12,-12), offset=Vec2(12,  0), neighbor_id="Drone-3"),
        DroneAgent("Drone-5", Vec2(24,-12), offset=Vec2(12,  0), neighbor_id="Drone-4"),
    ]
    swarm = SwarmFormation(agents, name="GridSweep")
    d = 1.0 / math.sqrt(2)  # diagonal unit step
    trajectory = (
        [Vec2(0.0, 1.5)] * 15 +    # forward march
        [Vec2(d*1.5, d*1.5)] * 8 + # 45° turn
        [Vec2(1.5, 0.0)] * 12       # right march
    )
    swarm.run(trajectory, print_interval=7)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("═" * 66)
    print("  FORMATION CONTROL PATTERN — Decentralized Swarm Coordination")
    print("═" * 66)
    print("\n  Pure physics simulation — no LLM needed for this pattern.")
    print("  Each drone's control loop: Sense → Desire → Error → Correct\n")

    demo1_line_formation()
    demo2_v_formation()
    demo3_obstacle_avoidance()
    demo4_grid_with_turn()

    print("═" * 66)
    print("  Key Takeaways")
    print("═" * 66)
    print()
    print("  1. Local rules → global shape: no drone sees the full formation")
    print("  2. Emergent resilience: avoidance cascades through the neighbor chain")
    print("  3. Tunable KP: higher gain = tighter tracking, oscillation risk")
    print("  4. Scalable: adding a drone means adding one edge to the neighbor graph")
    print("  5. Resilient to failures: if a drone drops, its successor closes the gap")
    print()
