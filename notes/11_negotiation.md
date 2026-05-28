# Agent Negotiation
## Structured Offer/Counter-Offer Protocol for Resource Conflict Resolution

---

## What Problem Does This Solve?

When two autonomous agents both need the same resource at the same time, there are two naive options:
1. **First-come, first-served** — whoever asked first wins; the other is blocked
2. **Central authority** — a supervisor decides; agents have no voice

Both approaches leave value on the table. The first ignores priorities. The second ignores the agents' private knowledge of their own flexibility.

Negotiation provides a third option: a structured protocol where agents communicate their constraints, propose compromises, and reach an agreement that **respects priorities while preserving as much of each agent's original preference as possible**. A low-priority TrainingAgent that can run any time between 2AM and midnight will always prefer to defer than to be blocked entirely.

---

## The Protocol — Four Phases

### Phase 1: Conflict Detection

The mediator (ResourceManagerAgent) receives all requests and identifies overlapping time windows:

```python
def _overlaps(s1, d1, s2, d2) -> bool:
    return s1 < s2 + d2 and s2 < s1 + d1
```

Two agents conflict if their windows intersect — even partially. A 2-hour window starting at 2AM and a 4-hour window starting at 3AM overlap by 1 hour.

### Phase 2: Priority-Ordered Granting

Requests are sorted by priority (descending), with alphabetical tie-breaking for determinism. The highest-priority agent always gets their preferred slot if it's available:

```python
sorted_agents = sorted(
    agents.values(),
    key=lambda a: (-a.request.priority, a.agent_id)
)
```

The first agent in this order rarely faces a conflict (since `confirmed` is empty). Subsequent agents are increasingly likely to find their slot already taken.

### Phase 3: Offer/Counter-Offer Loop

When a conflict is detected, the mediator asks the lower-priority agent to propose an alternative:

```
[Round 1] TrainingAgent: "I can defer to 04:00 (2h after AnalyticsAgent finishes)"
[Mediator]: Validates against all confirmed slots → ✅ no conflict → ACCEPT
```

Each agent's `generate_counter()` scans forward from the preferred start:

```python
for candidate in range(pref, pref + max_defer + 1):
    if candidate == pref:
        continue   # original slot is blocked
    if candidate + dur > 24:
        break
    if not any(_overlaps(candidate, dur, bs, bd) for bs, bd in all_blocked):
        return Offer(proposed_start=candidate, ...)
return None   # no valid slot within flexibility window
```

The agent proposes its earliest valid alternative. The mediator validates against ALL confirmed slots (not just the direct conflict), preventing a proposal from colliding with a third agent.

### Phase 4: Forced Resolution (Fallback)

If an agent returns `None` from `generate_counter()` — either because it is RIGID or because no slot falls within its flexibility window — the mediator steps in:

```python
def _force_slot(req, confirmed) -> Optional[tuple[int, int]]:
    for start in range(0, 24 - req.duration + 1):
        if not any(_overlaps(start, req.duration, s, e-s) for s, e in confirmed.values()):
            return (start, start + req.duration)
    return None   # truly no slot available (rare)
```

Forced resolution ignores the agent's preferences and flexibility. The outcome is marked `PARTIAL` (some forced) or `DEADLOCKED` (no slot found at all). The agent gets scheduled somewhere, but without its consent.

---

## Flexibility — The Agent's Negotiating Range

Each agent has a `flexibility` level that defines how far from its preferred start it will willingly move:

| Level | Name | Max Deferral | Behaviour |
|---|---|---|---|
| 0 | RIGID | 0 hours | Will not move under any circumstances |
| 1 | LOW | 2 hours | Can shift at most 2 hours |
| 2 | MEDIUM | 6 hours | Can shift up to 6 hours |
| 3 | HIGH | 20 hours | Effectively runs any time |

**RIGID agents**: when two RIGID agents conflict at equal priority, neither will negotiate. The mediator must force one of them to a different slot. This is the "deadlock" the pattern documents as a known failure mode.

**The flexibility constraint is a hard limit**: an agent with LOW flexibility that cannot find a valid slot within ±2 hours returns `None`, and forced resolution takes over. The agent is not coerced into accepting a slot far outside its operating constraints.

---

## Priority as the Tiebreaker

The ordering rule is simple: **higher priority agents preserve their preferences; lower priority agents adapt**.

```
AnalyticsAgent (HIGH, 2AM)  → confirmed at 2AM–4AM
BackupAgent (MEDIUM, 2AM)   → 2AM conflicts → proposes 4AM–7AM → confirmed
TrainingAgent (LOW, 2AM)    → 2AM and 4AM both conflict → proposes 7AM–11AM → confirmed
```

Each agent in the cascade only needs to see the slot immediately before it in the schedule. The mediator manages this by tracking `confirmed` and passing `all_blocked` as context to each counter-offer call.

---

## Maintenance Windows — Pre-Blocked Slots

Some slots are off-limits before any agent requests them (maintenance, backups, peak-hour reservation). These are represented as pre-populated entries in `confirmed`:

```python
for i, (mw_start, mw_dur) in enumerate(maintenance_windows):
    confirmed[f"_maintenance_{i}"] = (mw_start, mw_start + mw_dur)
```

Agents treat them identically to confirmed agent slots. The only difference is they are labelled `░` in the ASCII timeline (vs `█` for agents) and stripped from the final schedule dict.

This is the cleanest design: the mediator has one unified `confirmed` dict; maintenance windows are just facts in that dict. No special-case logic needed.

---

## The Audit Transcript

Every protocol step is recorded:

```python
{"type": "GRANT",    "agent": "AnalyticsAgent", "start": 2,  "end": 4,  "round": 0}
{"type": "CONFLICT", "agent": "TrainingAgent",  "preferred": 2, "blocked_by": ["AnalyticsAgent"]}
{"type": "COUNTER",  "agent": "TrainingAgent",  "round": 1, "start": 4, "end": 8,
                     "reasoning": "Deferring +2h to 04:00 [flex=HIGH]", "valid": True}
{"type": "ACCEPT",   "agent": "TrainingAgent",  "start": 4,  "end": 8}
```

This transcript answers every stakeholder question:
- "Why did TrainingAgent run at 4AM instead of 2AM?" → CONFLICT at 2AM blocked by AnalyticsAgent; counter-proposed 4AM in round 1, accepted.
- "Did the mediator make this decision or did the agent?" → The agent counter-proposed; the mediator validated and accepted.
- "Were any agents forced?" → Check for `type == "FORCED"` entries.

---

## Comparison with Consensus

Both patterns handle agent disagreement, but the scope is different:

| Dimension | Consensus | Negotiation |
|---|---|---|
| Domain | Numerical values (forecasts, estimates) | Resource slots (who gets what window) |
| Disagreement type | Different estimates of the same fact | Competing claims on the same resource |
| Resolution mechanism | Iterative averaging toward mean | Offer/counter-offer within flexibility |
| Bad actor handling | MAD outlier detection | Priority + forced resolution |
| Outcome type | Single agreed value | Schedule allocation |

---

## Pros and Cons

### Pros
- **Better than first-come-first-served**: priority determines who keeps their slot, not who asked first
- **Better than top-down assignment**: agents propose alternatives using their own knowledge of flexibility
- **Win-win when possible**: a HIGH-flex agent that can run any time always finds a solution without force
- **Explainability**: the full offer/counter-offer sequence is logged and auditable
- **Maintenance windows**: pre-blocked slots integrate cleanly as first-class constraints

### Cons
- **No guarantee**: RIGID agents with equal priority deadlock; forced resolution is a fallback, not a solution
- **Partial information**: agents propose based on what the mediator tells them; if a new agent confirms a slot between rounds, the counter-offer may need to be re-proposed
- **Gaming risk**: a rational agent with HIGH flexibility might declare LOW flexibility to preserve its preferred slot — the pattern has no mechanism to verify declared flexibility
- **Latency**: each round of offer/counter-offer takes time; deep cascades with many agents can be slow

---

## When to Use

✅ Use when:
- Multiple agents compete for a shared, scarce resource (GPU time, database locks, meeting rooms)
- Agents have heterogeneous priorities and flexibilities that should influence the outcome
- You need an audit trail of how the schedule was reached
- A "good enough" solution is acceptable — not necessarily globally optimal

❌ Avoid when:
- Real-time allocation is required — the protocol overhead is too high
- All agents are equally rigid — you'll always end up at forced resolution
- Global optimality matters — the greedy priority-order approach does not guarantee the minimum total deferral across all agents

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `negotiation.py` | GPU server scheduling — 6 agent types, priority-ordered granting, flex constraints, maintenance windows, forced resolution, ASCII timeline |

---

## Real-World Equivalents

- **Airport slot coordination**: airlines submit preferred landing/departure slots; a regulator detects conflicts and asks lower-priority operators to propose alternatives
- **Operating room scheduling**: elective surgeries are bumped by emergency cases; the elective surgeon's team proposes alternative theatre times within their constraints
- **Spectrum allocation**: mobile operators bid for frequency bands; regulators mediate conflicts between adjacent-band requests
- **Git merge conflicts**: two developers modified the same line; the merge tool presents the conflict, each developer proposes a resolution, and one is accepted
- **UN peacekeeping mandate negotiation**: member states with conflicting interests on a resolution engage in rounds of proposed amendments until consensus or a vote forces resolution
