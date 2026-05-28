# Resource Allocation
## Priority-Aware Dispatch with Anti-Starvation, Preemption, and Auction Bidding

---

## What Problem Does This Solve?

In a multi-agent system, agents compete for a finite pool of shared resources — robots, GPU workers, API rate-limit slots, database connections, or compute threads. Naively serving requests in arrival order (FIFO) ignores the fact that some tasks are far more valuable than others. A CRITICAL production-line stoppage should not wait behind a LOW-priority overnight report.

But pure priority ordering creates a new problem: a constant stream of HIGH tasks can starve LOW tasks indefinitely. And when an emergency arrives mid-execution, there is no mechanism to interrupt a running task.

Resource Allocation solves all three concerns in one pattern:
1. **Priority dispatch** — scarce resources go to the highest-impact tasks first
2. **Anti-starvation** — long-waiting low-priority tasks accumulate priority boosts
3. **Preemption** — CRITICAL tasks can forcibly interrupt a lower-priority running task

---

## Core Components

### ResourceRequest

```python
@dataclass
class ResourceRequest:
    request_id: str        # uuid hex
    agent_id: str
    priority: int          # 1=LOW, 2=MEDIUM, 3=HIGH, 4=CRITICAL
    task_name: str
    duration: int          # ticks to complete
    bid_tokens: int = 0    # for AUCTION mode
    submitted_at: int = 0
    started_at: int = -1
    completed_at: int = -1
    status: str = "PENDING"   # PENDING / RUNNING / COMPLETE / PREEMPTED
    age_boost: int = 0        # accumulated anti-starvation boost

    @property
    def effective_priority(self) -> int:
        return min(4, self.priority + self.age_boost)

    @property
    def wait_time(self) -> int:
        return self.started_at - self.submitted_at if self.started_at >= 0 else -1
```

`effective_priority` caps at 4 so LOW tasks can become HIGH after long waits, but cannot jump past CRITICAL.

### Resource

```python
@dataclass
class Resource:
    resource_id: str
    name: str
    status: str = "AVAILABLE"    # AVAILABLE / BUSY
    current_task: Optional[ResourceRequest] = None
    busy_until: int = -1
    total_busy_ticks: int = 0    # for utilisation calculation
    tasks_completed: int = 0
```

---

## Allocation Strategies

Three strategies share the same dispatcher — only the sort key differs:

| Strategy | Sort Key | Best For |
|---|---|---|
| PRIORITY_QUEUE | `(-effective_priority, submitted_at)` | Factory floors, medical systems — impact matters most |
| AUCTION | `(-bid_tokens, -effective_priority, submitted_at)` | Cloud compute, API slots — agents signal value via budget |
| FAIR_SHARE | `(submitted_at)` | Background jobs, equal agents — strict fairness |

The dispatcher is a single zip:
```python
available = [r for r in self.resources if r.status == "AVAILABLE"]
sorted_pending = self._sort_pending()
for req, res in zip(sorted_pending, available):
    self._assign(req, res)
```

Adding a new strategy requires only a new sort key — the dispatch loop is unchanged.

---

## Anti-Starvation

The problem: a steady stream of HIGH requests will always outrank a LOW request, potentially delaying it forever.

The solution: every `STARVATION_THRESHOLD` ticks (default 4) that a request spends in PENDING state, its `age_boost` increments by `BOOST_AMOUNT` (default 1). This lifts its `effective_priority`:

```
LOW (1) → waits 4 ticks → MEDIUM (2) → waits 4 more → HIGH (3) → waits 4 more → CRITICAL (4)
```

The progression is gradual and bounded. A LOW task can never skip the queue instantly — it must genuinely wait. But it will always eventually run.

```python
def _apply_starvation_boost(self):
    for req in self._pending:
        wait = self.sim_time - req.submitted_at
        new_boost = (wait // self.STARVATION_THRESHOLD) * self.BOOST_AMOUNT
        if new_boost > req.age_boost:
            req.age_boost = new_boost
            self._print_event("BOOST", req)
```

---

## Preemption

When a CRITICAL request arrives and all resources are busy, waiting is unacceptable. Preemption steals a resource from the lowest-priority running task:

```python
def _try_preempt(self, critical_req: ResourceRequest) -> bool:
    if any(r.status == "AVAILABLE" for r in self.resources):
        return False   # don't preempt if a free resource exists

    # Find resource with the lowest-priority running task
    victim_res = min(
        [r for r in self.resources if r.status == "BUSY"],
        key=lambda r: r.current_task.priority
    )
    
    # Only preempt if the victim is lower priority
    if victim_res.current_task.priority >= critical_req.priority:
        return False
    
    # Preempt: recalculate remaining duration, re-queue
    victim_task = victim_res.current_task
    victim_task.duration = victim_res.busy_until - self.sim_time
    victim_task.status = "PREEMPTED"
    victim_task.started_at = -1
    self._pending.append(victim_task)
    
    # Free the resource and assign to critical
    victim_res.status = "AVAILABLE"
    self._assign(critical_req, victim_res)
    return True
```

Preempted tasks are re-queued with their **remaining** duration — they don't restart from the beginning. This is the fairest possible outcome: the task is delayed, not discarded.

---

## Schedule and Fast-Forward

Agents can schedule requests for future ticks:

```python
allocator.schedule(at_tick=10, request_a, request_b)
```

The requests are injected into `_pending` when `sim_time == at_tick`. This models real-world scenarios where jobs arrive in batches (e.g., a nightly batch at midnight).

When no work is pending or running, the simulator fast-forwards to the next scheduled tick rather than burning through empty ticks:

```python
if not self._pending and not any(r.status == "BUSY" for r in self.resources):
    if self._scheduled:
        self.sim_time = min(self._scheduled.keys())
        continue
    else:
        break
```

This keeps demos readable without artificial delays in the output.

---

## Auction Mode

In AUCTION mode, agents declare a `bid_tokens` value when submitting their request. Higher bids win earlier access to the resource:

```python
# Sort key: (-bid_tokens, -effective_priority, submitted_at)
```

The agent with the most tokens runs first. This is useful when:
- Agents have different budgets that reflect real value
- You want to prevent low-budget agents from monopolising slots
- A chargeback model tracks token consumption per agent

Bid tokens are advisory — they don't change the duration or outcome, only the dispatch order. An agent with 0 tokens still runs eventually (once higher-bidding agents finish).

---

## The Tick Loop

The simulation advances one tick at a time. Each tick:

1. **Inject scheduled** — pull requests from `_scheduled[sim_time]` into `_pending`
2. **Complete tasks** — mark resources AVAILABLE for tasks whose `busy_until == sim_time`
3. **Anti-starvation** — boost long-waiting PENDING requests
4. **Dispatch** — sort pending, zip with available resources, assign

```python
def _tick(self):
    for req in self._scheduled.pop(self.sim_time, []):
        req.submitted_at = self.sim_time
        self._pending.append(req)

    for res in self.resources:
        if res.status == "BUSY" and res.busy_until == self.sim_time:
            self._complete(res)

    self._apply_starvation_boost()
    self._dispatch()
```

This ordering matters: complete first, then dispatch, so a newly freed resource can be claimed in the same tick a task finishes.

---

## Metrics

After the simulation, `print_metrics()` provides:

**Utilisation bar** (16 chars): `(total_busy_ticks / sim_ticks) * 16` filled blocks
```
AMR-1    ████████████████  100%  5 tasks
AMR-2    ████████░░░░░░░░   50%  3 tasks
```

**Per-agent wait table**: sorted by effective priority, with `★` for preempted tasks and `+N` for boosted tasks

**Summary stats**: total sim ticks, completed tasks, average wait

---

## Comparison with Agent Negotiation

Both patterns allocate resources to competing agents, but the approach differs:

| Dimension | Agent Negotiation | Resource Allocation |
|---|---|---|
| Protocol | Structured offer/counter-offer | Silent dispatcher (agents don't negotiate) |
| Agent role | Active — proposes alternatives | Passive — submits request and waits |
| Time model | Static 24-hour day | Dynamic tick simulation |
| Conflict resolution | Agents propose within flexibility | Dispatcher decides (preemption or queue) |
| Audit trail | Offer transcript | Event log (assign, complete, preempt, boost) |

Use Negotiation when agents have private knowledge about their own flexibility. Use Resource Allocation when the dispatcher has full authority and agents should not have a voice in scheduling.

---

## Pros and Cons

### Pros
- **Priority without starvation**: boosts guarantee every request eventually runs
- **Emergency response**: CRITICAL preemption handles real-time urgency
- **Multiple strategies**: PRIORITY_QUEUE / AUCTION / FAIR_SHARE from one class
- **Deterministic simulation**: tick-based, reproducible, no real threads
- **Transparent metrics**: utilisation and wait times expose bottlenecks

### Cons
- **No negotiation**: agents cannot express preferences about when they run
- **Preemption cost**: a preempted task wastes its already-completed work (partially mitigated by remaining-duration re-queue)
- **Starvation threshold is tuned**: wrong STARVATION_THRESHOLD can be too aggressive (frequent boosts dilute priority) or too slow (starvation occurs anyway)
- **No global optimality**: greedy dispatch is fast but not optimal; a planner could pack the schedule more efficiently
- **FAIR_SHARE ignores priority entirely**: not suitable when task impact genuinely differs

---

## When to Use

✅ Use when:
- Multiple agents share a finite pool of identical resources (robots, GPU workers, API slots)
- Some tasks are genuinely more urgent than others and should preempt
- You need a simple, auditable allocation policy with guaranteed forward progress
- Agents submit requests and should not need to negotiate

❌ Avoid when:
- Agents have private information about flexibility that should influence scheduling (use Negotiation)
- Tasks have complex dependencies that require planning (use Multi-Agent Planning)
- Resources are heterogeneous and task-resource affinity matters (use Contract-Net)

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `resource_allocation.py` | Smart factory AMR dispatcher — 4 demos covering priority queue, anti-starvation, preemption, auction |

---

## Real-World Equivalents

- **Factory robot dispatch**: AMRs (autonomous mobile robots) serve multiple production lines; CRITICAL line stoppages preempt routine goods transfer
- **Cloud GPU scheduling**: ML training jobs bid for GPU time; spot-instance interruption is preemption; reserved instances get priority
- **Hospital operating room scheduling**: emergency surgeries preempt elective procedures; anti-starvation prevents elective cases from being bumped forever
- **Database connection pools**: high-priority OLTP queries get connections before batch analytics jobs
- **Kubernetes pod scheduling**: priority classes, preemption, and resource quotas implement exactly this pattern at the infrastructure level
- **Airport gate management**: aircraft with CRITICAL status (medical emergency, fuel) preempt gates held for lower-priority arrivals
