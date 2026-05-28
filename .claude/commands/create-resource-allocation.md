Create a new Resource Allocation implementation for the following domain: $ARGUMENTS

Follow the Resource Allocation pattern exactly:

**Step 1 — Define ResourceRequest and Resource dataclasses**
- `ResourceRequest`: request_id (uuid hex), agent_id, priority (1–4), task_name, duration (ticks), bid_tokens=0, submitted_at=0, started_at=-1, completed_at=-1, status="PENDING", age_boost=0
  - `@property effective_priority`: `min(4, priority + age_boost)`
  - `@property wait_time`: `started_at - submitted_at` if `started_at >= 0` else `-1`
- `Resource`: resource_id, name, status="AVAILABLE", current_task=None, busy_until=-1, total_busy_ticks=0, tasks_completed=0

**Step 2 — Define constants**
```python
PRIORITY_NAME = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}
STARVATION_THRESHOLD = 4   # ticks in PENDING before boost
BOOST_AMOUNT = 1           # priority boost per threshold crossing
```

**Step 3 — Build ResourceAllocator**
- `__init__(resources, strategy="PRIORITY_QUEUE", allow_preemption=False)`
- `submit(*requests)` — set `submitted_at = sim_time`, add to `_pending`, call `_dispatch()`
- `schedule(at_tick, *requests)` — store in `_scheduled[at_tick]` dict
- `run(max_ticks=60)` — tick loop; fast-forward when idle and scheduled tasks exist
- `_tick()`:
  1. Inject `_scheduled[sim_time]` into `_pending`
  2. Complete tasks where `busy_until == sim_time`
  3. `_apply_starvation_boost()` on all PENDING requests
  4. `_dispatch()`
- `_dispatch()`:
  - PRIORITY_QUEUE: sort by `(-effective_priority, submitted_at)`
  - AUCTION: sort by `(-bid_tokens, -effective_priority, submitted_at)`
  - FAIR_SHARE: sort by `(submitted_at)`
  - Zip sorted pending with available resources, call `_assign()`
- `_assign(req, res)` — mark resource BUSY, set `busy_until`, update request `started_at`
- `_complete(res)` — mark resource AVAILABLE, update `completed_at`, `tasks_completed`
- `_try_preempt(critical_req) → bool`:
  - Only if all resources are BUSY
  - Find resource with lowest-priority running task
  - Preempt: `duration = busy_until - sim_time`, re-queue as PENDING
  - Assign critical to freed resource
- `_apply_starvation_boost()`:
  - Each PENDING request waiting `>= STARVATION_THRESHOLD` ticks → `age_boost += BOOST_AMOUNT`
  - Print BOOST event
- `print_metrics()`:
  - Sim stats (ticks, completed, avg wait)
  - Per-resource utilisation bar (16 chars)
  - Per-agent table (priority, wait, status, boost/preempt markers)

**Step 4 — Print helpers**
- `_print_header(resources, strategy)` — table of resources and strategy name
- `_print_event(event_type, ...)`:
  - `📥 SUBMIT` — request submitted
  - `🤖 ASSIGN` — resource → agent with tick range
  - `✅ COMPLETE` — finished (wait, duration)
  - `⚡ PREEMPT` — task preempted (remaining ticks, re-queued)
  - `⬆ BOOST` — anti-starvation boost applied

**Step 5 — Fast-forward idle logic**
```python
while self.sim_time < max_ticks:
    if not self._pending and not any(r.status == "BUSY" for r in self.resources):
        if self._scheduled:
            self.sim_time = min(self._scheduled.keys())
            continue
        else:
            break
    self._tick()
    self.sim_time += 1
```

**Step 6 — Four demos**
- Demo 1: PRIORITY_QUEUE, 3+ resources, 5+ requests at different priorities — verify HIGH runs before LOW
- Demo 2: Anti-starvation — 1 resource, LOW request submitted first, then HIGH stream arrives; LOW must eventually run via boost
- Demo 3: Preemption — 2 resources busy with MEDIUM when CRITICAL request arrives tick 2; verify preemption fires
- Demo 4: Auction — 2 resources, 4 agents with different bid_tokens; verify higher bid wins earlier slot

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/resource_allocation_<domain>.py
