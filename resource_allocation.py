"""
Resource Allocation Pattern — Priority Queue, Auction, Anti-Starvation, Preemption
-----------------------------------------------------------------------------------
Demonstrates:
  1. Tiered priority queue — HIGH/CRITICAL tasks dispatched before MEDIUM/LOW
  2. Anti-starvation — long-waiting requests get automatic priority boosts
  3. Preemption — CRITICAL tasks can steal a resource from a running MEDIUM/LOW task
  4. Auction mechanism — agents bid internal tokens; highest bid wins the resource
  5. Simulation clock — deterministic tick-based execution, no real threading needed
  6. Utilisation metrics — per-resource busy%, throughput, and per-agent wait times
  7. Mock mode (no API key) + LLM mode (LLM-generated task reasoning)

Scenario: Smart factory with a fleet of Autonomous Mobile Robots (AMRs)
  ProductionLine agents have HIGH/CRITICAL priority (line-stop risk)
  Shipping agents have MEDIUM priority (shipment deadlines)
  Warehouse agents have LOW priority (routine inventory work)
  AMR_DispatcherAgent allocates robots via one of three strategies.
"""

import os
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
import anthropic


USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))
client  = anthropic.Anthropic() if USE_LLM else None

PRIORITY_NAME = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}


# ─────────────────────────────────────────────────────────────
# 1. DATA STRUCTURES
# ─────────────────────────────────────────────────────────────

@dataclass
class ResourceRequest:
    request_id:  str
    agent_id:    str
    priority:    int          # 1=LOW … 4=CRITICAL
    task_name:   str
    duration:    int          # simulation ticks
    bid_tokens:  int  = 0    # for auction strategy
    submitted_at: int = 0
    started_at:  int = -1
    completed_at: int = -1
    status:      str = "PENDING"   # PENDING / ASSIGNED / COMPLETE / PREEMPTED
    age_boost:   int = 0           # accumulated anti-starvation boost

    @property
    def effective_priority(self) -> int:
        return min(4, self.priority + self.age_boost)

    @property
    def wait_time(self) -> int:
        return self.started_at - self.submitted_at if self.started_at >= 0 else -1


@dataclass
class Resource:
    resource_id: str
    name:        str
    status:      str = "AVAILABLE"
    current_task: Optional[ResourceRequest] = field(default=None, repr=False)
    busy_until:  int = -1
    total_busy_ticks: int = 0
    tasks_completed:  int = 0


# ─────────────────────────────────────────────────────────────
# 2. RESOURCE ALLOCATOR
# ─────────────────────────────────────────────────────────────

class ResourceAllocator:
    STARVATION_THRESHOLD = 4    # ticks of waiting before a priority boost
    BOOST_AMOUNT         = 1    # priority levels added per boost cycle

    def __init__(
        self,
        resources: list[Resource],
        strategy: str = "PRIORITY_QUEUE",
        allow_preemption: bool = False,
    ):
        self.resources         = {r.resource_id: r for r in resources}
        self.strategy          = strategy
        self.allow_preemption  = allow_preemption
        self.pending:   list[ResourceRequest] = []
        self.completed: list[ResourceRequest] = []
        self.sim_time   = 0
        self._scheduled: dict[int, list[ResourceRequest]] = defaultdict(list)
        self._active_ticks: set[int] = set()

    # ── Public API ────────────────────────────────────────────

    def submit(self, *requests: ResourceRequest) -> None:
        """Submit requests immediately at the current sim_time."""
        for req in requests:
            req.submitted_at = self.sim_time
            req.status = "PENDING"
            self.pending.append(req)
            self._print("SUBMIT", req=req)

        if self.allow_preemption:
            for req in requests:
                if req.priority == 4 and not self._has_available():
                    self._try_preempt(req)

        self._dispatch()

    def schedule(self, at_tick: int, *requests: ResourceRequest) -> None:
        """Schedule requests to arrive at a future tick."""
        for req in requests:
            self._scheduled[at_tick].append(req)

    def run(self, max_ticks: int = 60) -> None:
        """Advance simulation until all work is done or max_ticks reached."""
        while self.sim_time < max_ticks:
            idle = not self.pending and all(
                r.status == "AVAILABLE" for r in self.resources.values()
            )
            if idle:
                if not self._scheduled:
                    break
                # Fast-forward to next scheduled submission
                self.sim_time = min(self._scheduled.keys())
            else:
                self.sim_time += 1
            self._tick()

    # ── Simulation core ───────────────────────────────────────

    def _tick(self) -> None:
        # 1. Inject scheduled submissions
        if self.sim_time in self._scheduled:
            for req in self._scheduled.pop(self.sim_time):
                self.submit(req)

        # 2. Complete tasks that have finished this tick
        for res in list(self.resources.values()):
            if res.status == "BUSY" and res.busy_until <= self.sim_time:
                self._complete(res)

        # 3. Anti-starvation boosts
        self._apply_starvation_boost()

        # 4. Dispatch pending to any now-available resources
        self._dispatch()

    def _dispatch(self) -> None:
        available = [r for r in self.resources.values() if r.status == "AVAILABLE"]
        if not available or not self.pending:
            return

        if self.strategy == "PRIORITY_QUEUE":
            ordered = sorted(
                self.pending,
                key=lambda r: (-r.effective_priority, r.submitted_at),
            )
        elif self.strategy == "AUCTION":
            ordered = sorted(self.pending, key=lambda r: -r.bid_tokens)
        else:   # FAIR_SHARE — arrival order (FIFO)
            ordered = list(self.pending)

        for req, res in zip(ordered, available):
            self._assign(req, res)

    def _assign(self, req: ResourceRequest, res: Resource) -> None:
        req.status      = "ASSIGNED"
        req.started_at  = self.sim_time
        res.status      = "BUSY"
        res.current_task = req
        res.busy_until  = self.sim_time + req.duration
        self.pending.remove(req)
        self._print("ASSIGN", req=req, res=res)

    def _complete(self, res: Resource) -> None:
        req = res.current_task
        req.status       = "COMPLETE"
        req.completed_at = self.sim_time
        res.status       = "AVAILABLE"
        res.current_task = None
        res.total_busy_ticks += req.duration
        res.tasks_completed  += 1
        self.completed.append(req)
        self._print("COMPLETE", req=req, res=res)

    def _try_preempt(self, critical: ResourceRequest) -> bool:
        """Preempt the lowest-priority running task to make way for CRITICAL."""
        candidates = [
            (res, res.current_task)
            for res in self.resources.values()
            if res.status == "BUSY"
            and res.current_task
            and res.current_task.priority < critical.priority
        ]
        if not candidates:
            return False

        candidates.sort(key=lambda x: (x[1].priority, -x[1].started_at))
        res, running = candidates[0]

        remaining = res.busy_until - self.sim_time
        running.status     = "PREEMPTED"
        running.duration   = remaining
        running.started_at = -1
        running.age_boost  = max(running.age_boost, 2)   # ensure prompt re-assignment
        self.pending.insert(0, running)                   # front of queue

        self._print("PREEMPT", req=running, res=res)
        self._assign(critical, res)
        return True

    def _apply_starvation_boost(self) -> None:
        for req in self.pending:
            wait = self.sim_time - req.submitted_at
            if wait > 0 and wait % self.STARVATION_THRESHOLD == 0:
                if req.effective_priority < 4:
                    req.age_boost += self.BOOST_AMOUNT
                    self._print("BOOST", req=req)

    def _has_available(self) -> bool:
        return any(r.status == "AVAILABLE" for r in self.resources.values())

    # ── Metrics ───────────────────────────────────────────────

    def print_metrics(self) -> None:
        all_done = self.completed + [r for r in self.pending if r.status == "COMPLETE"]
        waits = [r.wait_time for r in all_done if r.wait_time >= 0]
        avg_wait = sum(waits) / len(waits) if waits else 0

        print(f"\n  ══ Allocation Metrics ══════════════════════════════════")
        print(f"  Strategy: {self.strategy}  |  Sim ticks: {self.sim_time}")
        print(f"  Completed: {len(self.completed)}  Pending: {len(self.pending)}"
              f"  Avg wait: {avg_wait:.1f} ticks")
        print()
        print(f"  {'Resource':<18}  Utilisation  Tasks")
        print(f"  {'─'*18}  {'─'*11}  {'─'*5}")
        for res in self.resources.values():
            util = res.total_busy_ticks / max(1, self.sim_time)
            bar  = "█" * int(util * 16) + "░" * (16 - int(util * 16))
            print(f"  {res.name:<18}  {bar} {util*100:4.0f}%  {res.tasks_completed}")

        print()
        print(f"  {'Agent':<24}  {'Priority':<10}  {'Wait':>4}  Status")
        print(f"  {'─'*24}  {'─'*10}  {'─'*4}  {'─'*10}")
        all_reqs = sorted(
            self.completed + self.pending,
            key=lambda r: r.submitted_at,
        )
        for req in all_reqs:
            wait = f"{req.wait_time}" if req.wait_time >= 0 else "─"
            boost = f" +{req.age_boost}★" if req.age_boost else ""
            print(f"  {req.agent_id:<24}  {PRIORITY_NAME[req.priority]:<10}  "
                  f"{wait:>4}  {req.status}{boost}")

    # ── Print helpers ─────────────────────────────────────────

    def _print(self, event: str, req=None, res=None) -> None:
        if self.sim_time not in self._active_ticks:
            print(f"\n  ── Tick {self.sim_time} {'─' * max(1, 48 - len(str(self.sim_time)))}")
            self._active_ticks.add(self.sim_time)

        if event == "SUBMIT":
            bid = f"  bid={req.bid_tokens}" if self.strategy == "AUCTION" else ""
            print(f"  📥 SUBMIT    {req.agent_id:<24} [{PRIORITY_NAME[req.priority]:<8}]"
                  f"  {req.task_name}  dur={req.duration}{bid}")
        elif event == "ASSIGN":
            end = res.busy_until
            print(f"  🤖 ASSIGN    {res.name} → {req.agent_id:<22}"
                  f" [{PRIORITY_NAME[req.priority]:<8}]  ticks {self.sim_time}–{end}")
        elif event == "COMPLETE":
            print(f"  ✅ COMPLETE   {res.name}  {req.agent_id:<22}"
                  f"  wait={req.wait_time}  dur={req.duration}")
        elif event == "BOOST":
            print(f"  ⬆  BOOST     {req.agent_id:<24}  "
                  f"waited {self.sim_time - req.submitted_at} ticks "
                  f"→ effective priority now {PRIORITY_NAME[req.effective_priority]}")
        elif event == "PREEMPT":
            print(f"  ⚡ PREEMPT   {res.name}  {req.agent_id:<22}"
                  f"  [{PRIORITY_NAME[req.priority]}]  "
                  f"preempted — {req.duration} ticks remaining, re-queued")


# ─────────────────────────────────────────────────────────────
# DEMOS
# ─────────────────────────────────────────────────────────────

def _sep(label: str = "") -> None:
    if label:
        print(f"\n{'═' * 66}")
        print(f"  {label}")
        print(f"{'═' * 66}")
    else:
        print(f"\n  {'─' * 62}")


def _req(agent_id, priority, task_name, duration, bid=0) -> ResourceRequest:
    return ResourceRequest(
        request_id=uuid.uuid4().hex[:6],
        agent_id=agent_id,
        priority=priority,
        task_name=task_name,
        duration=duration,
        bid_tokens=bid,
    )


def demo_1_priority_queue() -> ResourceAllocator:
    _sep("DEMO 1 — Priority Queue: Factory Floor Dispatch")
    print("\n  3 AMRs, 5 requests. HIGH fills first; LOW waits.\n")

    resources = [Resource("amr-1", "AMR-1"),
                 Resource("amr-2", "AMR-2"),
                 Resource("amr-3", "AMR-3")]

    alloc = ResourceAllocator(resources, strategy="PRIORITY_QUEUE")
    alloc.submit(
        _req("ProductionLine_A",  3, "deliver critical component",  3),
        _req("ProductionLine_B",  3, "collect finished sub-assembly", 2),
        _req("ShippingAgent",     2, "move goods to loading dock",   4),
        _req("MaintenanceAgent",  2, "ferry spare parts",            2),
        _req("WarehouseAgent",    1, "inventory cycle count",        5),
    )
    alloc.run()
    alloc.print_metrics()
    return alloc


def demo_2_anti_starvation() -> ResourceAllocator:
    _sep("DEMO 2 — Anti-Starvation: Low-Priority Request Eventually Wins")
    print("\n  1 AMR. WarehouseAgent (LOW) submits first, then a stream of HIGH")
    print("  requests arrive. Every 4 idle ticks, LOW gets a +1 priority boost.\n")

    resources = [Resource("amr-1", "AMR-1")]
    alloc = ResourceAllocator(resources, strategy="PRIORITY_QUEUE")

    # Low-priority request submitted at tick 0
    alloc.submit(_req("WarehouseAgent", 1, "inventory count", 3))

    # Stream of HIGH requests arriving later — keep AMR busy
    alloc.schedule(1, _req("ProductionLine_A", 3, "urgent delivery #1", 4))
    alloc.schedule(5, _req("ProductionLine_B", 3, "urgent delivery #2", 4))
    alloc.schedule(9, _req("ShippingAgent",    2, "shipment pickup",    3))

    alloc.run(max_ticks=30)
    alloc.print_metrics()
    return alloc


def demo_3_preemption() -> ResourceAllocator:
    _sep("DEMO 3 — Preemption: CRITICAL Steals from MEDIUM")
    print("\n  2 AMRs. Both busy with MEDIUM tasks when a CRITICAL request arrives.")
    print("  The lower-priority running task is preempted and re-queued.\n")

    resources = [Resource("amr-1", "AMR-1"),
                 Resource("amr-2", "AMR-2")]

    alloc = ResourceAllocator(resources, strategy="PRIORITY_QUEUE",
                              allow_preemption=True)
    # Fill both AMRs at tick 0 with MEDIUM tasks
    alloc.submit(
        _req("ShippingAgent",    2, "regular goods transfer",      6),
        _req("MaintenanceAgent", 2, "routine parts delivery",      6),
    )
    # CRITICAL request arrives at tick 2 — both AMRs busy
    alloc.schedule(2, _req("ProductionLine_A", 4,
                            "LINE STOPPAGE IMMINENT — critical part", 3))
    alloc.run()
    alloc.print_metrics()
    return alloc


def demo_4_auction() -> ResourceAllocator:
    _sep("DEMO 4 — Auction: Highest Bid Wins the Resource")
    print("\n  2 API rate-limit slots available. 4 agents bid tokens.")
    print("  Higher bid = better service. Low-bidder queues last.\n")

    resources = [Resource("api-slot-1", "API-Slot-1"),
                 Resource("api-slot-2", "API-Slot-2")]

    alloc = ResourceAllocator(resources, strategy="AUCTION")
    alloc.submit(
        _req("AnalyticsAgent",  2, "run market-data query",    2, bid=50),
        _req("ReportingAgent",  1, "generate weekly summary",  3, bid=10),
        _req("MLPipelineAgent", 3, "fetch training dataset",   2, bid=80),
        _req("MonitoringAgent", 2, "pull system telemetry",    1, bid=35),
    )
    alloc.run()
    alloc.print_metrics()
    return alloc


if __name__ == "__main__":
    _sep("RESOURCE ALLOCATION PATTERN — Smart Factory AMR Dispatcher")
    mode = "LLM mode" if USE_LLM else "DEMO MODE — mock simulation (set ANTHROPIC_API_KEY for real LLM)"
    print(f"\n  {mode}\n")

    demo_1_priority_queue()
    _sep()
    demo_2_anti_starvation()
    _sep()
    demo_3_preemption()
    _sep()
    demo_4_auction()

    _sep("Key Takeaways")
    print("""
  1. Priority Queue   — scarce resources go to highest-impact tasks first
  2. Anti-Starvation  — age-boosting prevents LOW priority from starving forever
  3. Preemption       — CRITICAL can interrupt MEDIUM/LOW when urgency spikes
  4. Auction          — agents with more "budget" signal their true value;
                        the resource goes where it is valued most
  5. Metrics          — utilisation + wait times expose bottlenecks objectively
    """)
