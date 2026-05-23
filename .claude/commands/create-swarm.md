Create a new Swarm Architecture implementation for the following domain: $ARGUMENTS

Follow the Swarm pattern exactly:

**Step 1 — Define the Task model and StatusEnum**
- `TaskStatus` enum: include a transitional lock status between each real status
  - Example: `NEW → CLAIMED → PROCESSED → DRAFTING → DRAFTED → COMPLETE`
  - Lock statuses (CLAIMED, DRAFTING, etc.) prevent race conditions
- `Task` dataclass: task_id, payload, status, claimed_by, data dict, history list
- `Task.log(agent, message)` method for append-only audit trail

**Step 2 — Build the TaskBoard**
- Use `threading.Lock()` for all mutations
- `post(payload) → Task` — creates task with status=NEW
- `claim(task_id, agent, from_status, to_status) → bool` — atomic, returns False if race lost
- `update(task_id, agent, new_status, data_updates)` — updates status + data
- `get_tasks_by_status(status) → list[Task]`

**Step 3 — Build the base SwarmAgent**
- Extend `threading.Thread` with `daemon=True`
- `run()` loop: call `poll_and_work()` every 0.5s until `_stop` event is set
- `stop()` method to gracefully shut down

**Step 4 — Build specialized agents (minimum 3)**
- Each extends SwarmAgent
- Each `poll_and_work()` must:
  1. Call `get_tasks_by_status(TARGET_STATUS)`
  2. For each task: attempt `board.claim(...)` — skip if False (race lost)
  3. Execute domain logic
  4. Call `board.update(...)` with next status
  5. Handle exceptions → set status to FAILED
- Deploy 2 instances of the first agent to demonstrate race-condition safety

**Step 5 — Demo**
- Post 3+ tasks simultaneously to show parallel processing
- Start all agents, run monitor loop until all tasks are COMPLETE or FAILED
- Print full audit trail for each task showing the emergent workflow
- Output should make it visible which agent claimed which task

**Critical rules:**
- Agents must never call each other — only read/write the board
- Atomic claiming (transitional lock status) is mandatory
- The workflow sequence must emerge from status transitions, not be hardcoded

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/swarm_<domain>.py
