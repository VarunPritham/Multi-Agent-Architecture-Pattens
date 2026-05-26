# Multi-Agent Planning
## Goal Decomposition + Dependency-Aware Execution

---

## What Problem Does This Solve?

A high-level goal like "launch a new product" or "generate a market analysis report" is not directly executable. No single agent can do it. Before any agent acts, the system needs to answer three questions:

1. What are the sub-tasks required to achieve this goal?
2. Which agent should handle each sub-task?
3. In what order must they execute — and which can run in parallel?

Multi-Agent Planning addresses this by inserting a **decomposition step** before execution. The output is a **Plan** — a first-class artifact with tasks, dependencies, and assignments — that guides the entire execution.

---

## The Plan as a First-Class Artifact

Unlike the Supervisor pattern (where the workflow is hardcoded) or the Swarm pattern (where it emerges from status transitions), Multi-Agent Planning makes the execution structure **explicit and inspectable**:

```
Plan: Generate market analysis for Product X
  ○ T1: gather_sales_data          [DataRetrieverAgent]   ← parallel
  ○ T2: analyze_competitor_chatter [SocialMediaAgent]     ← parallel
  ○ T3: summarize_analyst_reports  [FinancialDocsAgent]   ← parallel
  ○ T4: synthesize_findings        [ReportWriterAgent]    ← depends on T1, T2, T3
  ○ T5: executive_summary          [SummaryAgent]         ← depends on T4
```

You can inspect this plan before execution, log it, store it, or pass it to a human for review. If execution fails, you know exactly where and why.

---

## The Dependency Graph — The Core Data Structure

Tasks declare their dependencies explicitly:

```python
SubTask("T4", "Synthesise findings", "ReportWriterAgent", depends_on=["T1", "T2", "T3"])
```

The executor resolves this at runtime — no hardcoded sequencing needed:

```python
def ready_tasks(self) -> list[SubTask]:
    for task in self.tasks.values():
        deps_done = all(self.tasks[dep].status == COMPLETE for dep in task.depends_on)
        if deps_done:
            task.status = READY
            yield task
```

**Why this matters**: adding a new task with no dependencies automatically makes it run in parallel. Adding a task that depends on an existing one automatically sequences it correctly. The executor logic never changes — only the plan data changes.

---

## Parallel Execution via ThreadPoolExecutor

The standard library `concurrent.futures.ThreadPoolExecutor` is the right tool for this:

```python
with ThreadPoolExecutor(max_workers=4) as executor:
    while not plan.is_complete():
        ready = plan.ready_tasks()
        for task in ready:
            future = executor.submit(run_task, task)
            futures[future] = task

        done, _ = wait(futures, FIRST_COMPLETED)
        for future in done:
            task = futures.pop(future)
            task.result = future.result()
            task.status = COMPLETE
```

T1, T2, T3 have no dependencies → all three submit simultaneously → run in parallel. T4 has `depends_on: [T1, T2, T3]` → only becomes READY after all three complete → submits then.

**Latency impact**:
- Sequential: T1 + T2 + T3 + T4 + T5 = 5 × 2s = 10s
- With parallel execution: max(T1, T2, T3) + T4 + T5 = 2s + 2s + 2s = 6s

For real LLM calls (5–15 seconds each), the parallelism benefit is significant.

---

## Context Flow — Downstream Tasks Use Upstream Results

Synthesis tasks need the outputs of their dependencies. The executor passes completed results as context:

```python
context = plan.successful_results()   # {task_id → result string}
result  = agent.run(task.description, context)
```

The ReportWriterAgent receives the sales data, competitor analysis, and financial summaries all at once. It doesn't need to call those agents — it just receives their results through the plan's context mechanism.

---

## Dynamic Replanning — Adapting to Failures

A static plan that crashes on any failure is brittle. The replanning mechanism handles failures gracefully:

```
T2 fails (API rate limit)
    ↓
_replan() called
    ↓
T4 (depends on T2) → marked SKIPPED
T5 (depends on T4) → marked SKIPPED (cascade)
    ↓
T1 and T3 continue → COMPLETE
    ↓
Plan status: PARTIAL (not FAILED — some work succeeded)
```

**Levels of replanning sophistication:**

| Level | What happens on failure |
|---|---|
| Basic | Cascade SKIPPED to dependents, continue with independent tasks |
| Intermediate | Retry failed task with exponential backoff |
| Advanced | Re-call PlanningAgent with remaining goal + completed results → new sub-plan |
| Expert | Assign failed task to a backup agent from a pool |

---

## LLM-Based Decomposition — Dynamic Plans

For static workflows, a hardcoded plan is fine. For truly dynamic goal decomposition, use LLM tool_use:

```python
response = client.messages.create(
    tools=[{"name": "create_plan", "input_schema": {
        "tasks": [{"task_id", "description", "assigned_agent", "depends_on"}]
    }}],
    messages=[{
        "content": f"Decompose: '{goal}'\nAgents: {available_agents}\n"
                   f"Independent tasks use depends_on: []"
    }]
)
```

This means the same planning system can handle "launch a product" and "debug a server incident" by producing different plans with different task structures — without any code changes.

---

## Comparison: Multi-Agent Planning vs Other Patterns

| Pattern | Workflow source | Adaptable to failure? | Parallel execution? |
|---|---|---|---|
| Supervisor | Hardcoded in orchestrator | Manual rewrite | Only if coded explicitly |
| Swarm | Emerges from status | Yes (agents retry) | Yes (concurrent polling) |
| Blackboard | Emerges from facts | Yes (new facts change eligibility) | Yes (per cycle) |
| **Multi-Agent Planning** | **Decomposed from goal** | **Yes (dynamic replanning)** | **Yes (dependency graph)** |

Multi-Agent Planning is the most explicit: you can read the plan, explain it to a human, and trace exactly why each task ran when it did.

---

## Pros and Cons

### Pros
- **Efficiency**: parallel execution of independent tasks reduces total latency
- **Specialisation**: each agent handles only what it's best at
- **Transparency**: the plan is a readable artifact — explainable and auditable
- **Flexibility**: LLM decomposition generates different plans for different goals

### Cons
- **Coordination overhead**: planning step adds latency before any work begins
- **Rigidity risk**: a static plan cannot adapt if the environment changes mid-execution
- **Decomposition quality**: a bad plan (wrong dependencies, wrong agent assignments) leads to bad results

---

## When to Use

✅ Use when:
- The goal is complex and not directly executable by one agent
- You have 3+ specialised agents that need to collaborate
- Some tasks are clearly independent (parallelism opportunity)
- You need the execution path to be inspectable and explainable

❌ Avoid when:
- The workflow is always the same and well-understood (use Supervisor — simpler)
- The goal is simple enough for a single LLM call
- Ultra-low latency is required — the decomposition step adds overhead

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `multi_agent_planning.py` | Full market analysis pipeline — PlanningAgent, PlanExecutor, dependency DAG, parallel execution, dynamic replanning on failure |

---

## Real-World Equivalents

- **Film production**: producer creates a shooting schedule (plan); cinematography, costume, and set design run in parallel; editing depends on all of them
- **Software sprint planning**: PM decomposes the release goal into tickets with dependencies; frontend and backend work in parallel; QA gates on both
- **NASA mission control**: mission director decomposes a launch into parallel readiness checks; countdown only proceeds when all gates clear
- **Consulting engagement**: partner decomposes "advise on market entry" into parallel research workstreams that synthesise into a final deck
