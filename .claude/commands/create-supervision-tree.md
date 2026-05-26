Create a new Supervision Tree with Guarded Capabilities implementation for the following domain: $ARGUMENTS

Follow the Supervision Tree pattern exactly:

**Step 1 — Define the tool registry**
- List all tools available in the system as a flat dict: `{name: callable}`
- Separate them by sensitivity: standard tools, sensitive tools (email/comms), critical tools (billing/admin)
- Sensitive and critical tools should only appear in the RootSupervisor's tool set

**Step 2 — Build BaseAgent**
- `allowed_tools: dict[str, Callable]` field — the capability guard
- `use_tool(name, *args)` — checks whitelist, raises `PolicyViolationError` if not found
- `mark_crashed(error)` — records crash timestamp, sets status to CRASHED
- `recent_crash_count(window_seconds) → int` — for backoff calculation
- `restart()` — resets state, sets status back to RUNNING

**Step 3 — Build SupervisorAgent (extends BaseAgent)**
- `spawn_child(cls, id, tool_names)` — enforces child tools ⊆ supervisor tools via PermissionError
- `monitor_loop()` — iterates children, calls `_handle_failure()` on CRASHED or POLICY_VIOLATION
- `_handle_failure(child)`:
  1. Log the incident
  2. Check backoff (3 crashes in 10s = stop)
  3. Apply strategy: ONE_FOR_ONE / ONE_FOR_ALL / ESCALATE

**Step 4 — Build at least 2 branch supervisors and 4+ worker agents**
Design the tree so each branch has a clearly different capability set:
- Branch A: external/risky tools (web scraping, code execution, API calls)
- Branch B: internal/safe tools (storage, summarisation, formatting)

Worker agents should:
- Use `self.use_tool()` for everything — never call tools directly
- Raise exceptions freely — no try/except inside the agent

**Step 5 — Inject all three failure modes in the demo**
- ONE_FOR_ONE scenario: one agent crashes, siblings untouched
- Policy violation: agent attempts a tool outside its allowed set
- Crash loop: agent crashes repeatedly → backoff engages after threshold

**Step 6 — Verify capability guard explicitly**
After the demo runs, show the guard working:
```python
try:
    branch_supervisor.spawn_child(WorkerAgent, "rogue", ["admin_tool"])
except PermissionError as e:
    print(f"BLOCKED — {e}")
```

**Step 7 — Print incident log summary**
Show counts by incident type (CRASH, POLICY_VIOLATION, RESTART, BACKOFF) and the full timestamped log.

**Critical rules:**
- Agents crash freely — supervisors recover
- Supervisors never do domain work
- Capability inheritance is strict: you can only grant what you have

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/supervision_<domain>.py
