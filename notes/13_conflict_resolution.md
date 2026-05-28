# Conflict Resolution
## Structured Detection and Multi-Strategy Mediation for Competing Agent Plans

---

## What Problem Does This Solve?

As autonomous agents pursue their objectives, their planned actions will sometimes collide. A ThroughputAgent wants to advance a loan batch while a FairnessAgent needs to hold it for review. Two robot arms try to move into the same workspace simultaneously. A BullAgent recommends buying a stock while a BearAgent recommends shorting the same one.

Letting agents proceed with conflicting actions causes:
- **Deadlocks** — neither agent can make progress
- **Physical damage** — robots occupy the same space
- **Logical inconsistency** — the system holds contradictory states simultaneously
- **Suboptimal outcomes** — whichever agent "wins" by speed rather than by legitimacy

Conflict Resolution provides a structured mechanism: a SupervisorAgent intercepts plans before execution, detects conflicts, mediates using one of four strategies, and records the full reasoning in an audit trail.

---

## The Four Resolution Strategies

### 1. Policy-Based Resolution (default)

Predefined rules govern outcomes deterministically. Policies are evaluated in priority order; the first matching policy wins.

```python
@dataclass
class Policy:
    policy_id:   str
    name:        str
    description: str
    priority:    int   # higher = evaluated first
    condition:   Callable[[Plan, Plan], Optional[Tuple[Plan, Plan]]]
    # Returns (approved, denied) if applicable, else None
```

**When to use**: compliance-critical systems, regulated industries, anywhere the logic needs to be auditable and modifiable without touching agent code.

**Loan processing example**: policy POL-001 states any HOLD_FOR_FAIRNESS_REVIEW plan has precedence over ADVANCE_TO_APPROVAL. The supervisor simply checks this rule — it doesn't need to understand either agent's goals.

### 2. Hierarchical Resolution

The agent with the higher `priority` value wins. Tie-breaks go to the plan submitted first (plan_a).

```python
winner, loser = (a, b) if a.priority >= b.priority else (b, a)
```

**When to use**: safety-critical systems where authority chains are established (e.g., a CRITICAL manufacturing arm always takes workspace priority over MEDIUM maintenance), or as the fallback when no policy matches.

**Note**: pure priority ordering is fast and predictable but zero-sum — the losing agent is simply denied. No compromise is attempted.

### 3. Negotiation

The higher-priority agent holds its slot. The lower-priority agent iteratively proposes alternative actions until one is accepted or max rounds are exhausted.

```python
for rnd in range(1, MAX_ROUNDS + 1):
    counter = flex_agent.propose_counter(original_action, rnd)
    if counter is None:
        _escalate(conflict); return
    if not _actions_still_conflict(counter, fixed.action):
        # AGREEMENT — outcome = MODIFIED_BOTH
        return
# Exhausted → escalate
```

`propose_counter` is the agent's only voice in the process. RIGID agents return None immediately. Flexible agents scan their option space across rounds:
- Round 1: SELL_REDUCED_POSITION — still SELL-type, still conflicts with BUY
- Round 2: HEDGE_WITH_OPTIONS — neutral instrument, accepted

`_actions_still_conflict` uses domain heuristics (keyword opposition for finance, exclusive zone checks for robotics). It must be tuned to the domain.

**When to use**: agents have private knowledge about flexibility that the supervisor doesn't. Best when a "less-lose" outcome is achievable and agents are sophisticated enough to propose alternatives.

### 4. Game-Theoretic Resolution

The conflict is modeled as a 2-player game. A payoff matrix provided in plan metadata defines the outcome of every strategy combination. The system finds all pure-strategy Nash equilibria — states where no agent benefits by deviating unilaterally — and assigns the equilibrium with the highest combined payoff.

```python
for sa in strategies_a:
    for sb in strategies_b:
        pa, pb = payoffs[sa][sb]
        a_can_improve = any(payoffs[sa2][sb][0] > pa for sa2 ≠ sa)
        b_can_improve = any(payoffs[sa][sb2][1] > pb for sb2 ≠ sb)
        if not a_can_improve and not b_can_improve:
            nash.append((sa, sb, pa, pb))
best = max(nash, key=lambda x: x[2]+x[3])
```

**GPU cluster example**:
```
                    DEMAND_ALL   SHARE_FAIRLY
DEMAND_ALL           (-5,-5)       (+3,+1)
SHARE_FAIRLY         (+1,+3)       (+4,+4)
```

Check (SHARE_FAIRLY, SHARE_FAIRLY):
- MLTrainerAgent deviates to DEMAND_ALL → gets +3 vs +4 → cannot improve ✓
- InferenceAgent deviates to DEMAND_ALL → gets +3 vs +4 → cannot improve ✓
→ Unique Nash equilibrium. Both assigned SHARE_FAIRLY. Combined payoff +8 vs the -10 they'd get by both demanding all.

**When to use**: highly complex resource contention where agents are rational and self-interested but can be "guided" to cooperate by formalizing the payoffs. Computationally intensive for large strategy spaces but principled.

---

## Conflict Detection

The supervisor maintains `_active_plans: Dict[target, Plan]`. On every `submit_plan`:

```python
def _detect_conflict(self, incoming: Plan) -> Optional[Conflict]:
    existing = self._active_plans.get(incoming.target)
    if existing is None or existing.status == PlanStatus.DENIED:
        return None

    # Exclusive resource: both agents claim sole access
    if existing.metadata.get("exclusive") or incoming.metadata.get("exclusive"):
        if existing.agent_id != incoming.agent_id:
            return Conflict(existing, incoming, ConflictType.RESOURCE)

    # Different actions on same target → goal conflict
    if existing.action != incoming.action:
        return Conflict(existing, incoming, ConflictType.GOAL)

    return None
```

**ConflictType taxonomy**:
| Type | Trigger | Example |
|---|---|---|
| RESOURCE | exclusive flag + different agents | Two agents both set `exclusive=True` on same GPU cluster |
| GOAL | same target, different actions | ADVANCE_TO_APPROVAL vs HOLD_FOR_FAIRNESS_REVIEW |
| TEMPORAL | overlapping exclusive time windows | (extend detection for time-window plans) |
| LOGICAL | contradictory system state requirements | ENABLE_FAILOVER vs DISABLE_FAILOVER |

---

## Escalation: The Human-in-the-Loop Fallback

When automated resolution fails — no policy matches and negotiation exhausts all rounds, or no Nash equilibrium exists — the supervisor escalates:

```python
def _escalate(self, conflict: Conflict):
    conflict.plan_a.status = PlanStatus.ESCALATED
    conflict.plan_b.status = PlanStatus.ESCALATED
    # Both plans held; no action taken
```

The audit trail records the escalation with full context: which agents conflicted, which strategy was attempted, and why it failed. A human operator can review and provide a final judgment.

**Design principle**: escalation is never silent. The audit trail must answer:
- What conflict occurred?
- Which strategy was attempted?
- Why did it fail?
- What does the human operator need to decide?

---

## The Audit Trail

Every resolution is recorded as an AuditEntry:

```python
@dataclass
class AuditEntry:
    conflict_id:    str            # uuid for traceability
    conflict_type:  str            # RESOURCE / GOAL / etc.
    agents:         Tuple[str, str]
    strategy:       str            # which resolver was used
    outcome:        str            # APPROVED_A / APPROVED_B / MODIFIED_BOTH / ESCALATED
    reasoning:      str            # human-readable explanation
    approved_plans: List[str]      # plan_ids that proceeded
    denied_plans:   List[str]      # plan_ids that were blocked
```

This answers stakeholder questions:
- "Why was ThroughputAgent blocked?" → Policy POL-001 FAIRNESS_CHECK_REQUIRED took precedence.
- "Who made this decision?" → Automated policy resolution via SupervisorAgent.
- "Were any conflicts escalated to humans?" → Check for ESCALATED outcomes.
- "What strategies were tried before escalation?" → Strategy field traces the path.

---

## Clear Target: Lifecycle Management

When a task completes, its target must be released so other agents can claim it:

```python
supervisor.clear_target("LoanBatch-LB-2024-047")
```

Without this, the first approved plan for a target "occupies" it forever, blocking all subsequent plans even after the task has long since finished. In production systems, clear_target is called by a task completion handler or watchdog.

---

## Comparison with Related Patterns

| Pattern | Relationship |
|---|---|
| **Agent Negotiation** | A specialised form of Conflict Resolution's negotiation strategy — the full offer/counter-offer protocol with flexibility tiers and maintenance windows |
| **Resource Allocation** | Prevents conflicts by a single dispatcher; Conflict Resolution handles conflicts that slipped through or involve goals rather than just resource slots |
| **Supervisor Architecture** | Conflict Resolution's hierarchical strategy *is* the supervisor pattern applied to plan conflicts |
| **Consensus** | Resolves numerical disagreements iteratively; Conflict Resolution handles action-level contradictions |

---

## Pros and Cons

### Pros
- **Coherence**: prevents the system from entering contradictory or deadlocked states
- **Safety**: physical and logical collisions are blocked before execution
- **Flexibility**: four strategies cover the full range from top-down authority to emergent cooperation
- **Auditability**: every decision is logged with reasoning — essential for regulated systems
- **Escalation path**: no conflict is silently dropped; humans remain the ultimate fallback

### Cons
- **Latency**: detection and resolution add overhead; not suitable for real-time tight-loop control
- **Policy maintenance**: for large systems, the policy framework can become complex to manage
- **Negotiation gaming**: rational agents may declare themselves RIGID to preserve preferred actions — no verification mechanism
- **Game-theoretic complexity**: payoff matrices must be defined for every conflict type; expensive for large strategy spaces
- **No global optimality**: each conflict is resolved locally; the globally optimal schedule across all agents may not be found

---

## When to Use

✅ Use when:
- Multiple agents act on shared targets with no pre-negotiated allocation
- Some conflicts are known in advance (policies) and others are dynamic (negotiation/game theory)
- Compliance, safety, or audit requirements demand an explainable decision trail
- You need both top-down authority (policies/hierarchy) and bottom-up compromise (negotiation)

❌ Avoid when:
- Real-time tight-loop control is required (overhead is too high)
- All conflicts can be prevented upfront by design (Resource Allocation or Contract-Net)
- Agents are purely cooperative with no competing objectives

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `conflict_resolution.py` | Loan processing, robot arm, trading conflict, cloud GPU — all four strategies demonstrated |

---

## Real-World Equivalents

- **Air traffic control**: two aircraft filed conflicting flight plans; controller applies separation rules (policy) or instructs one to climb/descend (hierarchical)
- **Hospital OR scheduling**: emergency surgery vs. elective procedure conflict; triage policy always grants emergency priority
- **Git merge conflict**: two developers modified the same file; merge tool detects conflict and prompts for manual resolution (escalation) or uses auto-merge rules (policy)
- **Corporate resource allocation**: two departments request the same meeting room; booking system applies seniority rules (hierarchical) or asks one team to propose alternatives (negotiation)
- **Spectrum allocation**: two mobile operators want the same frequency band; regulator applies spectrum policy or facilitates auction (game-theoretic)
- **Database transaction isolation**: conflicting writes trigger locking/rollback mechanisms (the protocol-level equivalent of this pattern)
