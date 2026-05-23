# Swarm Architecture
## Emergent Decentralized Coordination

---

## What Problem Does This Solve?

Some workflows are too dynamic, too parallel, or too resilience-critical for a single orchestrator. You need:
- Tasks to be processed in parallel without a central bottleneck
- The system to keep running even if individual agents fail
- New agents to be addable without touching any existing code
- The workflow to adapt dynamically, not follow a rigid pre-programmed sequence

The Swarm solves this by removing the orchestrator entirely. Coordination happens through a shared task board and status transitions — no agent tells another what to do.

---

## The Core Mechanism

```
TaskBoard (shared state — the only "authority")
    │
    ├── Task: status="new"       ← ResearchAgent sees this, claims it
    ├── Task: status="researched" ← DraftingAgent sees this, claims it
    └── Task: status="drafted"    ← EditorAgent sees this, claims it
```

Agents run as independent threads. Each polls the board looking for tasks in their target status. When they find one, they:
1. Atomically claim it (status → transitional lock)
2. Execute their work
3. Update status to the next phase

Nobody programmed "research first, then draft, then edit." That sequence *emerged* because:
- Research outputs `status="researched"`
- DraftingAgent only triggers on `status="researched"`
- DraftingAgent outputs `status="drafted"`
- EditorAgent only triggers on `status="drafted"`

The status enum *is* the workflow definition.

---

## Atomic Claiming — Preventing Race Conditions

Without proper claiming, two ResearchAgents could grab the same task:

```
Time T1: Agent-1 reads task (status="new") → about to claim
Time T2: Agent-2 reads task (status="new") → about to claim
Time T3: Both claim → duplicate work
```

**The fix: transitional lock statuses**

```python
def claim(task_id, agent, from_status, to_status) -> bool:
    with self._lock:                       # mutex
        task = self._tasks[task_id]
        if task.status == from_status:     # still available?
            task.status = to_status        # atomic transition to lock status
            return True
        return False                       # another agent beat us
```

Status transitions:
```
NEW → CLAIMED → RESEARCHED → DRAFTING → DRAFTED → EDITING → COMPLETE
```
`CLAIMED`, `DRAFTING`, `EDITING` are transitional locks — tasks in these states are invisible to other agents of the same type.

---

## Why Redundant Agents Are a Feature, Not a Bug

In a Supervisor, two workers of the same type would be wasteful. In a Swarm, they're the resilience mechanism:

```python
agents = [
    ResearchAgent("ResearchAgent-1", board),
    ResearchAgent("ResearchAgent-2", board),   # redundant — if -1 crashes, -2 picks up
    DraftingAgent("DraftingAgent-1", board),
    EditorAgent("EditorAgent-1", board),
]
```

If `ResearchAgent-1` crashes mid-task, the task stays in `CLAIMED` status. A timeout mechanism (not shown but important in production) can reset `CLAIMED → NEW` after a timeout, allowing `ResearchAgent-2` to pick it up.

---

## The Audit Trail Proves Emergence

```
[19:32:39] ResearchAgent-1  — Claimed (NEW → CLAIMED)
[19:32:39] ResearchAgent-1  — Updated status → RESEARCHED
[19:32:39] DraftingAgent-1  — Claimed (RESEARCHED → DRAFTING)
[19:32:39] DraftingAgent-1  — Updated status → DRAFTED
[19:32:39] EditorAgent-1    — Claimed (DRAFTED → EDITING)
[19:32:39] EditorAgent-1    — Updated status → COMPLETE
```

Nobody orchestrated this. The sequence is purely a result of each agent polling and claiming tasks in its target status.

---

## Horizontal Scaling

In a Supervisor, scaling means making the orchestrator faster — which is hard. In a Swarm, scaling means adding agents:

```python
# 10x throughput: just add more agents
agents = [ResearchAgent(f"R-{i}", board) for i in range(5)]
agents += [DraftingAgent(f"D-{i}", board) for i in range(3)]
agents += [EditorAgent(f"E-{i}", board) for i in range(2)]
```

No other code changes. The task board handles the distribution.

---

## Adding a New Capability

In a Supervisor, adding a new step means modifying the orchestrator. In a Swarm:

1. Add a new status to `TaskStatus`: `RESEARCHED → FACT_CHECKED → DRAFTING`
2. Create a `FactCheckAgent` that triggers on `RESEARCHED`, outputs `FACT_CHECKED`
3. Start it as a thread

Zero changes to ResearchAgent, DraftingAgent, EditorAgent, or the TaskBoard.

---

## Pros and Cons

### Pros
- **Resilience**: no single point of failure; system runs even with agent failures
- **Scalability**: add capacity by spawning more agent instances
- **Extensibility**: new agent types require no changes to existing code
- **Parallelism**: multiple tasks processed simultaneously across the swarm

### Cons
- **Debuggability**: non-linear flow is harder to trace than a supervisor's sequential log
- **Governance**: enforcing business rules is harder without a central authority
- **Ordering guarantees**: if strict sequential order is required, you need careful status design
- **Stuck tasks**: a task in a transitional lock status with a crashed agent needs a timeout/recovery mechanism

---

## Production Considerations

**Claim timeout recovery:**
Tasks stuck in `CLAIMED`/`DRAFTING` etc. for too long should be reset to the previous stable status. Add a `claimed_at` timestamp and a background job that resets stale claims.

**Event-driven polling:**
In production, replace polling with pub/sub (Redis streams, Kafka). The board posts a message when a task's status changes; agents subscribe to their target status.

**Persistent board:**
In-memory board loses all tasks on crash. Use Redis or a DB-backed task queue in production.

---

## When to Use

✅ Use when:
- Tasks are parallel and independent (not dependent on each other's results)
- High resilience is required (no single point of failure acceptable)
- The domain is creative or dynamic (content, research, analysis)
- You need to scale processing by adding instances, not by upgrading hardware

❌ Avoid when:
- Steps are strictly sequential with critical dependencies (use Supervisor)
- Compliance/auditability requires clear chain of command (Supervisor is cleaner)
- You need guaranteed ordering across task phases

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `swarm_architecture.py` | Full content creation swarm — 3 agent types, atomic claiming, parallel tasks, audit trail |

---

## Real-World Equivalents

- **Wikipedia editing**: no editor-in-chief; contributors self-select articles needing work
- **Open source pull request queue**: developers claim issues, submit PRs, reviewers pick up ready PRs
- **Restaurant kitchen (expo model)**: each station watches for tickets in their category, not directed by the chef per-dish
