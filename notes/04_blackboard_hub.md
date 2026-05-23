# Blackboard Knowledge Hub
## Iterative Convergence via Shared Knowledge

---

## What Problem Does This Solve?

Some problems don't have a known solution path upfront. You can't design a sequential workflow because you don't know what steps are needed until you see the data. You need:
- Multiple specialists contributing partial knowledge incrementally
- Each specialist's contribution to potentially unlock new specialists
- The system to converge on a solution through accumulation, not execution
- A complete, auditable chain of how the answer was reached

The Blackboard solves this by replacing the workflow with a knowledge repository. Agents don't execute steps — they post what they know, and the presence of certain facts on the board is what triggers the next wave of agents.

---

## The Fundamental Difference from Other Patterns

| Pattern | Question answered | Coordination mechanism |
|---------|-------------------|----------------------|
| Supervisor | "What step comes next?" | Orchestrator decides |
| Swarm | "Who can do this task?" | Task status on board |
| Blackboard | "What do we know so far?" | Facts on board trigger agents |

In Supervisor/Swarm, you're executing a workflow. In Blackboard, you're **building knowledge** until you have enough to conclude.

---

## The Three Components

### 1. The Blackboard

A central, append-only repository of typed facts:

```
F001 [SYMPTOM    ] ER_Intake           conf=100%  "Fever + rash + conjunctivitis"
F002 [HYPOTHESIS ] SymptomAgent        conf=85%   "Consistent with viral infection"
F003 [ASSESSMENT ] DermatologyAgent    conf=80%   "Maculopapular — viral exanthem"
F004 [TEST_REQ   ] VirologyAgent       conf=95%   "Request IgM serology"
F005 [LAB_RESULT ] PathologyAgent      conf=95%   "IgM measles positive"
F006 [DIAGNOSIS  ] InfectiousDiseaseAg conf=92%   "Measles — confirmed"
```

Key properties:
- **Append-only**: facts are never deleted or changed — only superseded by new facts
- **Typed**: every fact has a `FactType` — agents can filter for exactly what they need
- **Confidence-weighted**: 0.0–1.0 score on every fact — prevents low-confidence facts from triggering subsequent agents
- **Provenance**: every fact records which agent posted it and when

### 2. Knowledge Sources (Agents)

Each agent has two methods:

**`is_eligible() → bool`** — reads the board, returns True if this agent should contribute now
- "Do facts exist that I can add value to?"
- Checks fact types, keywords, confidence levels
- Must include `not self._done` to prevent contributing twice

**`contribute()`** — reads the board, posts new facts, sets `self._done = True`
- Reads existing facts for context
- Uses its domain expertise (LLM call) to generate new insights
- Posts one or more typed, confidence-scored facts
- Never calls other agents

### 3. The Controller

Runs cycles until convergence:

```python
for cycle in range(MAX_CYCLES):
    eligible = [ks for ks in agents if ks.is_eligible()]
    if not eligible:
        break                    # no progress possible
    for ks in eligible:
        ks.contribute()
    if board.check_convergence():
        break                    # solution found
```

---

## Eligibility Conditions — The Cascade Design

The most critical design task is defining what triggers each agent. The chain should cascade naturally:

```
SYMPTOM exists
    → SymptomAnalysisAgent (always first)
        posts HYPOTHESIS containing "viral"
            → DermatologyAgent (triggered by "rash" in HYPOTHESIS/SYMPTOM)
            → VirologyAgent (triggered by "viral" in HYPOTHESIS at ≥65% conf)
                posts TEST_REQUEST
                    → PathologyAgent (triggered by TEST_REQUEST)
                        posts LAB_RESULT
                            → InfectiousDiseaseAgent (triggered by LAB_RESULT + viral HYPOTHESIS)
                                posts DIAGNOSIS
                                    → Controller detects convergence
```

**Confidence gating is critical.** Without it:
- A 30%-confidence "viral?" hypothesis triggers the virology specialist
- The specialist builds on a shaky foundation
- The final diagnosis inherits the uncertainty

With `min_confidence=0.65` on the virology trigger:
- The specialist only engages when there's solid evidence
- Weak hypotheses don't cascade

---

## Convergence — When Do We Stop?

The convergence check should require:
1. At least one CONCLUSION/DIAGNOSIS fact at or above a confidence threshold (e.g., 75%)
2. A minimum number of supporting facts (e.g., 3 hypotheses/assessments/lab results at ≥60%)

```python
def check_convergence(self) -> bool:
    diagnoses  = self.get_facts(FactType.DIAGNOSIS, min_confidence=0.75)
    supporting = self.get_facts(min_confidence=0.6)  # all high-conf facts
    return len(diagnoses) >= 1 and len(supporting) >= 3
```

If no agent posts a high-confidence diagnosis, the system runs `MAX_CYCLES` and returns the best available conclusion.

---

## The Append-Only Rule

Why are facts never deleted?

**Traceability**: every hypothesis that led to the diagnosis is preserved. This is the "chain of thought" — legally and medically important.

**No race conditions on deletes**: two agents can safely post simultaneously without corrupting each other's facts.

**Explicit supersession**: if a hypothesis turns out wrong, a new fact says so ("Previous viral hypothesis inconsistent with lab results — now suspected bacterial") rather than erasing history.

---

## The Audit Trail — The Pattern's Superpower

```
  F001  [SYMPTOM    ] ER_Intake            conf=100%  "Fever + rash..."
  F002  [HYPOTHESIS ] SymptomAnalysisAgent conf=85%   "Viral or bacterial..."
  F003  [ASSESSMENT ] SymptomAnalysisAgent conf=90%   "Onset 3 days ago..."
  F004  [ASSESSMENT ] DermatologyAgent     conf=80%   "Maculopapular spread..."
  F005  [HYPOTHESIS ] DermatologyAgent     conf=75%   "No vesicular lesions..."
  F006  [HYPOTHESIS ] VirologyAgent        conf=82%   "Classic prodrome..."
  F007  [TEST_REQUEST] VirologyAgent       conf=95%   "Request IgM serology"
  F008  [LAB_RESULT ] PathologyAgent       conf=88%   "Leukopenia..."
  F009  [LAB_RESULT ] PathologyAgent       conf=95%   "IgM measles positive"
★ F010  [DIAGNOSIS  ] InfectiousDiseaseAg  conf=92%   "Measles confirmed"
  F011  [ASSESSMENT ] InfectiousDiseaseAg  conf=95%   "Isolate, Vitamin A..."
```

This is explainable AI in practice. You can answer:
- "Why measles and not rubella?" → F006 shows the prodrome pattern, F009 shows IgM positive
- "Why did virology run?" → F004 and F002 show viral hypothesis at >65% confidence
- "Who ordered the blood test?" → F007, VirologyAgent

No other pattern produces this level of traceability automatically.

---

## Pros and Cons

### Pros
- **Handles ill-defined problems**: no need to know the solution path upfront
- **Incremental knowledge building**: partial answers accumulate into a full solution
- **Full traceability**: every inference is preserved with agent provenance and confidence
- **Non-linear flexibility**: any agent can trigger at any point if the conditions are met

### Cons
- **Latency**: multiple LLM calls in sequential cycles; slower than direct dispatch
- **Controller bottleneck**: the cycle loop is single-threaded in the basic implementation
- **Blackboard bloat**: without a "forgetting mechanism," old or irrelevant facts degrade agent performance over time
- **Unpredictable path**: harder to predict exactly how many cycles will be needed

---

## Production Considerations

**Forgetting mechanism**: periodically prune facts below a confidence threshold, or facts that have been explicitly superseded. Otherwise the board becomes a noisy scratchpad.

**Sharding**: for high-throughput systems, partition the board by fact type — agents only subscribe to the types they care about.

**Parallel cycles**: if multiple agents are eligible in cycle N and they don't depend on each other's outputs, they can run concurrently.

---

## When to Use

✅ Use when:
- The problem is ill-defined — you don't know the steps upfront
- Multiple weak specialists must combine their knowledge to reach a strong conclusion
- The reasoning chain must be explainable (medical, legal, fraud detection)
- New information mid-process should change what happens next

❌ Avoid when:
- The workflow is sequential and known (use Supervisor — simpler and faster)
- Tasks are independent (use Swarm)
- Low latency is critical — controller cycles add significant overhead
- The problem is simple enough for a single LLM call

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `blackboard_hub.py` | Full medical diagnosis — 5 specialist agents, confidence-gated cascade, convergence detection, full audit trail |

---

## Real-World Equivalents

- **Hospital diagnostic war room**: specialists write findings on a whiteboard; other specialists react to what they see
- **Intelligence analysis**: analysts post partial findings; other analysts trigger when they see relevant data
- **Fraud detection**: pattern agents post signals; risk agents synthesize when enough signals accumulate
- **Scientific peer review**: reviewers each post assessments; editor synthesizes when sufficient consensus exists
