# Supervisor Architecture
## Centralized Orchestration

---

## What Problem Does This Solve?

A complex task requires multiple sequential steps, each handled by a different specialist. You need to:
- Ensure steps happen in the right order
- Make conditional decisions based on each step's result (halt if step 2 fails)
- Maintain a single source of accountability
- Produce an auditable log of the process

Without a supervisor, you'd have agents calling each other in chains — brittle, hard to debug, impossible to add error handling consistently.

---

## The Core Structure

```
User
  │
  ▼
OrchestratorAgent  ←── owns the workflow, makes all decisions
  │
  ├── Step 1: DocumentValidationAgent.run(input)
  │     └── if invalid → REJECT immediately
  │
  ├── Step 2: CreditCheckAgent.run(input)
  │     └── if score < 600 → REJECT immediately
  │
  ├── Step 3: RiskAssessmentAgent.run(input, credit_report)
  │     └── gets risk level, recommendation
  │
  └── Step 4: make_final_decision(risk_assessment) → FinalResult
```

The orchestrator is the only agent that knows the workflow. Workers know nothing about each other or what comes before/after them.

---

## The "No God Agent" Rule

The most common mistake: letting the orchestrator do domain work.

**Wrong:**
```python
class LoanOrchestrator:
    def handle(self, app):
        # Orchestrator doing domain work — BAD
        if "W2" not in app.documents and app.income > 100000:
            score = app.income * 0.3 - app.existing_debts
            ...
```

**Right:**
```python
class LoanOrchestrator:
    def handle(self, app):
        # Orchestrator only coordinates — GOOD
        validation = self.doc_validator.run(app)
        if validation.status != "valid":
            return self._reject(f"Missing: {validation.missing_docs}")

        credit = self.credit_checker.run(app)
        ...
```

The orchestrator should only contain:
- Calls to workers
- If/else branching on worker results
- Checkpoint operations
- The `_reject()` helper

All business logic lives in the workers.

---

## Structured Handoffs — Why Pydantic Is Non-Negotiable

Every worker must return a typed model, not a string or dict.

**Without Pydantic:**
```python
result = validator.run(app)
if result["status"] != "valid":  # KeyError waiting to happen
    ...
```

**With Pydantic:**
```python
class ValidationResult(BaseModel):
    status: str        # "valid" | "invalid"
    missing_docs: list[str]
    notes: str

result = validator.run(app)
if result.status != "valid":    # type-checked, IDE-complete, never KeyError
    ...
```

The orchestrator's branching is deterministic only when it receives structured data. Free-text responses from workers make the orchestrator fragile.

---

## Checkpointing — The Safety Net

The orchestrator is a single point of failure. If it crashes between step 2 and step 3, you need to resume from step 2's output — not start over.

```python
def handle_application(self, app):
    checkpoint = self._load_checkpoint(app.id)

    # Step 1 — skip if already done
    if "validation" not in checkpoint:
        validation = self.doc_validator.run(app)
        self._save_checkpoint(app.id, "validation", validation.model_dump())
    else:
        validation = ValidationResult(**checkpoint["validation"])

    # Step 2 — skip if already done
    if "credit" not in checkpoint:
        credit = self.credit_checker.run(app)
        self._save_checkpoint(app.id, "credit", credit.model_dump())
    else:
        credit = CreditReport(**checkpoint["credit"])

    # ... continue
```

**Checkpoint storage**: JSON file per task ID. In production: a database (Redis, Postgres) with the job ID as key.

---

## Error Handling at the Orchestrator Level

Workers should raise exceptions on failure. The orchestrator catches them and decides what to do:

```python
try:
    credit = self.credit_checker.run(app)
except TimeoutError:
    # Option 1: retry
    credit = self.credit_checker.run(app)
except CreditBureauUnavailableError:
    # Option 2: route to backup agent
    credit = self.fallback_checker.run(app)
except Exception as e:
    # Option 3: reject gracefully
    return self._reject(f"Credit check failed: {e}")
```

Workers never handle retry logic — that's the orchestrator's job.

---

## Pros and Cons

### Pros
- **Predictability**: clear, linear flow — easy to trace, monitor, and explain
- **Governance**: all business rules live in one place (the orchestrator)
- **Debuggability**: if something goes wrong, you look at the orchestrator's log

### Cons
- **Single point of failure**: orchestrator crashes = entire workflow halts
- **Bottleneck**: all tasks funnel through one process; can't scale workers independently
- **Rigidity**: adding a new step requires modifying the orchestrator

---

## When to Use

✅ Use when:
- The workflow is sequential with known steps
- The domain is regulated (finance, healthcare, legal) — auditability is required
- Partial completion is dangerous (don't proceed if step N fails)
- You need to enforce business rules centrally

❌ Avoid when:
- Steps are independent and can run in parallel (use Swarm)
- The path forward is unknown upfront (use Blackboard)
- You need the system to continue if one component fails (use Swarm)

---

## Comparison: Supervisor vs Swarm

| Dimension | Supervisor | Swarm |
|-----------|-----------|-------|
| Control | Orchestrator pushes tasks | Agents pull from board |
| Failure | Orchestrator down = system down | Any agent fails = others continue |
| Sequence | Pre-programmed | Emerges from status transitions |
| Adding capacity | Add more worker types (orchestrator unchanged) | Just add more agent instances |
| Debugging | Single log to follow | Follow the task's audit trail |
| Best for | Sequential, regulated workflows | Parallel, resilient, creative tasks |

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `supervisor_architecture.py` | Full loan approval workflow — 3 workers, conditional branching, checkpointing, error handling |

---

## Real-World Equivalents

- **Hospital ICU**: attending physician (orchestrator) directs lab, radiology, pharmacy (workers)
- **Assembly line**: line manager (orchestrator) sequences each station (workers)
- **Legal review process**: partner (orchestrator) assigns research, drafting, compliance review (workers)
