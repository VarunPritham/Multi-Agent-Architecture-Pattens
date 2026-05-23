Create a new Supervisor (Orchestrator) Architecture implementation for the following workflow: $ARGUMENTS

Follow the Supervisor pattern exactly:

**Step 1 — Define all Pydantic schemas**
- One input model for the orchestrator (the top-level task)
- One output model per worker (what each worker returns)
- One final result model (what the orchestrator returns)
- All fields must be typed — no raw dicts passed between agents

**Step 2 — Build worker agents**
- Create one class per step in the workflow
- Each class has a single `run(input)` method that returns its typed output model
- Workers must not call each other or the orchestrator
- Workers should use LLM calls (with mock fallback) to simulate domain intelligence

**Step 3 — Build the orchestrator**
- Constructor instantiates all workers — it owns their lifecycle
- Implement `_save_checkpoint(step_name, data)` — saves to `.checkpoints/<task_id>.json`
- Implement `_load_checkpoint(task_id)` — resumes from last completed step
- Implement `_reject(reason)` — standardized rejection response
- Main method: `handle_<task>(input)` — the full sequential workflow

**Step 4 — Implement the workflow**
- Check checkpoint at start — skip completed steps
- After each step: call `_save_checkpoint()` before proceeding
- Include at least 2 conditional branches (`if result.field < threshold: return self._reject(...)`)
- Clean up checkpoint file on successful completion

**Step 5 — Demo**
- Include 3 cases in `if __name__ == "__main__":`
  - 1 happy path (all steps pass)
  - 1 early rejection (fails at step 1 or 2)
  - 1 late rejection (passes early steps, fails at final gate)

**Critical rules:**
- The orchestrator must contain ALL conditional logic
- No worker should make any workflow decisions
- No worker should know about any other worker

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/supervisor_<domain>.py
