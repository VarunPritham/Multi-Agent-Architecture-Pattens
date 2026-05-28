Create a new Conflict Resolution implementation for the following domain: $ARGUMENTS

Follow the Conflict Resolution pattern exactly:

**Step 1 — Define Plan, Conflict, Policy, AuditEntry dataclasses**
- `Plan`: plan_id (uuid hex), agent_id, target, action, priority (1–4), metadata (dict), status=PROPOSED, denial_reason=""
  - `label() → str`: formatted one-liner for printing
- `Conflict`: plan_a, plan_b, conflict_type (RESOURCE/GOAL/TEMPORAL/LOGICAL), conflict_id (uuid hex), resolved=False, resolution_strategy, resolution_outcome="", reasoning="", rounds=0
- `Policy`: policy_id, name, description, priority (int), condition: `Callable[[Plan, Plan], Optional[Tuple[Plan, Plan]]]`
- `AuditEntry`: conflict_id, conflict_type, agents, strategy, outcome, reasoning, approved_plans (list), denied_plans (list)

**Step 2 — Define constants**
```python
PRIORITY_NAME = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}
```
Also define `PlanStatus` enum: PROPOSED / APPROVED / DENIED / MODIFIED / ESCALATED
And `ResolutionStrategy` enum: HIERARCHICAL / POLICY_BASED / NEGOTIATION / GAME_THEORETIC
And `ConflictType` enum: RESOURCE / GOAL / TEMPORAL / LOGICAL

**Step 3 — Build ConflictingAgent base + minimum 4 domain specialists**
- `propose(target, action, **metadata) → Plan`
- `on_approved(plan)`, `on_denied(plan)`, `on_modified(plan, new_action)`
- `propose_counter(blocked_action, round_num) → Optional[str]` — None = rigid (default)
- At least one specialist must override `propose_counter` to return alternatives over ≥2 rounds
- At least one specialist must remain rigid (returns None) to trigger escalation

**Step 4 — Build SupervisorAgent**
- `register_agent(*agents)`, `add_policy(policy)` (sorted by priority desc)
- `submit_plan(plan, strategy)` — detect conflict, resolve immediately
- `clear_target(target)` — release target when task completes
- `_detect_conflict(incoming) → Optional[Conflict]`:
  - Check `_active_plans[target]`; if exclusive metadata → RESOURCE conflict
  - If different actions on same target → GOAL conflict
- `_resolve(conflict, strategy)` — dispatch to one of four methods
- `_hierarchical_resolve`: winner = higher priority; tie-break = plan_a (submitted first)
- `_policy_resolve`: iterate policies in priority order; first match wins; fallback to hierarchical
- `_negotiation_resolve`:
  - Fixed = higher priority plan; flexible = the other
  - Loop up to MAX_ROUNDS=4: call `flex_agent.propose_counter()`
  - LLM path: `propose_alternative` tool_use → `{alternative_action, reasoning}`
  - `_actions_still_conflict(counter, fixed_action)` → domain heuristic (e.g., SELL vs BUY keywords)
  - If valid → MODIFIED_BOTH; if None or rounds exhausted → escalate
- `_game_theoretic_resolve`:
  - Read `payoff_matrix` from plan metadata (dict of dicts: `strategy_a → strategy_b → (pa, pb)`)
  - Find all pure-strategy Nash equilibria (neither player improves by deviating unilaterally)
  - Assign strategies from Nash with highest combined payoff → MODIFIED_BOTH
  - No Nash found → escalate
- `_escalate(conflict)`: mark both plans ESCALATED, record audit
- `_approve(plan)`, `_deny(plan, reason)`, `_record_audit(conflict)`
- `print_audit_trail()`: per-conflict table with conflict_id, agents, strategy, outcome, reasoning

**Step 5 — Print helpers**
- `_hdr(title, subtitle)` — section header with `═══` border
- Event symbols inline in each resolver:
  - ✅ GRANTED/APPROVED, ⚡ CONFLICT, 🏛 HIERARCHICAL, 📋 POLICY, 🤝 NEGOTIATION, 🎮 GAME-THEORETIC
  - ✗ DENIED, ↩ COUNTER (round N), ⚠ ESCALATED, ☠ max rounds exceeded

**Step 6 — Four demos**
- Demo 1: policy-based — compliance/safety agent vs efficiency agent; policy grants compliance
- Demo 2: hierarchical — two same-role agents at different priorities; higher wins
- Demo 3: negotiation — equal-priority agents; flexible one proposes 2 rounds before agreement
- Demo 4: game-theoretic — two agents with exclusive resource claim; payoff_matrix in metadata; Nash assigns both SHARE_FAIRLY (or domain equivalent)

**Payoff matrix format for Demo 4:**
```python
payoff_matrix = {
    "STRATEGY_A1": {"STRATEGY_B1": (pa, pb), "STRATEGY_B2": (pa, pb)},
    "STRATEGY_A2": {"STRATEGY_B1": (pa, pb), "STRATEGY_B2": (pa, pb)},
}
```
Pass in plan metadata: `plan = agent.propose(target, action, exclusive=True, payoff_matrix=payoff_matrix)`

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/conflict_resolution_<domain>.py
