Create a new Multi-Agent Planning implementation for the following domain: $ARGUMENTS

Follow the Multi-Agent Planning pattern exactly:

**Step 1 — Define TaskStatus, PlanStatus enums, and SubTask/Plan models**
- `TaskStatus`: PENDING, READY, RUNNING, COMPLETE, FAILED, SKIPPED
- `PlanStatus`: DRAFT, EXECUTING, COMPLETE, PARTIAL, FAILED
- `SubTask` dataclass: task_id, description, assigned_agent, depends_on (list[str]), status, result, error, started_at, completed_at
- `Plan` dataclass with:
  - `tasks: dict[str, SubTask]`
  - `ready_tasks()` — returns tasks whose all dependencies are COMPLETE; auto-skips tasks whose deps FAILED
  - `is_complete()` — all tasks in terminal status
  - `successful_results()` — dict of task_id → result for COMPLETE tasks

**Step 2 — Build worker agents (minimum 4, domain-specific)**
- One agent per research/execution domain appropriate to the use case
- Each has `run(task_description: str, context: dict = None) → str`
- Context receives upstream results so synthesis tasks can reference them
- Include mock results and LLM fallback

**Step 3 — Build PlanningAgent**
- `decompose(goal, available_agents) → Plan`
- LLM path: use tool_use to generate structured task list with `depends_on` fields
  - Prompt must instruct: independent tasks use `depends_on: []`, they run in parallel
  - Final synthesis task depends on all data-gathering tasks
- Mock path: return a hard-coded Plan appropriate to the domain (for demo without API key)

**Step 4 — Build PlanExecutor**
- `execute(plan) → dict` using `concurrent.futures.ThreadPoolExecutor`
- Main loop:
  1. `ready = plan.ready_tasks()` — tasks with all deps COMPLETE
  2. Submit all ready tasks to thread pool
  3. `wait(futures, FIRST_COMPLETED)` — process results as they finish
  4. On success: update status to COMPLETE, store result
  5. On failure: update status to FAILED, call `_replan(plan, failed_task)`
  6. Repeat until `plan.is_complete()`
- `_replan(plan, failed_task)`: cascade SKIPPED to all direct dependents; log the adaptation

**Step 5 — Build the Orchestrator**
- Constructor: instantiate PlanningAgent and PlanExecutor
- Main method: decompose → (optionally inject failure) → execute → summarise → return final output
- The final output is the result of the last synthesis task

**Step 6 — Visualise the plan**
- Before execution: print the task DAG with status icons and dependency arrows
- During execution: print each task start (agent, deps) and completion (duration, result preview)
- After execution: print summary table (task_id, agent, status, duration)

**Step 7 — Two demos**
- Demo 1: full happy path — all tasks succeed, show parallel execution clearly
- Demo 2: inject a failure in a mid-plan task — show cascade skip and PARTIAL plan outcome

**Plan DAG requirements:**
- Minimum 4 tasks
- At least 2 tasks must run in parallel (depends_on: [])
- At least 1 task must depend on multiple predecessors (synthesis task)
- At least 1 multi-level chain (T_n depends on T_n-1 which depends on something)

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/multi_agent_planning_<domain>.py
