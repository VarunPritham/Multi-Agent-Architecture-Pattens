"""
Conflict Resolution — Pattern 13
Structured detection and multi-strategy mediation for competing agent plans.

Four resolution strategies:
  1. Policy-Based    — predefined compliance rules govern outcome deterministically
  2. Hierarchical    — supervisor imposes priority-ordered decision
  3. Negotiation     — agents propose compromises; escalates only when rigid
  4. Game-Theoretic  — Nash equilibrium aligns self-interest with global optimum

Demos:
  1. Loan processing        — FairnessAgent vs ThroughputAgent (policy wins)
  2. Robot arm workspace    — two manufacturing agents (priority wins)
  3. Financial trading      — BUY vs SELL_SHORT (2-round negotiation)
  4. Cloud GPU allocation   — competing exclusive claims (Nash → SHARE_FAIRLY)
"""

from __future__ import annotations
import os, uuid
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Callable
from enum import Enum

USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))

# ── Enumerations ───────────────────────────────────────────────────────────────

class ConflictType(Enum):
    RESOURCE = "RESOURCE"   # two agents claim the same finite resource
    GOAL     = "GOAL"       # opposing objectives on the same target
    TEMPORAL = "TEMPORAL"   # overlapping exclusive time windows
    LOGICAL  = "LOGICAL"    # mutually exclusive system-state requirements

class ResolutionStrategy(Enum):
    HIERARCHICAL   = "HIERARCHICAL"    # supervisor imposes priority-based decision
    POLICY_BASED   = "POLICY_BASED"    # predefined rules govern outcome
    NEGOTIATION    = "NEGOTIATION"     # iterative offer/counter-offer
    GAME_THEORETIC = "GAME_THEORETIC"  # Nash equilibrium over payoff matrix

class PlanStatus(Enum):
    PROPOSED  = "PROPOSED"
    APPROVED  = "APPROVED"
    DENIED    = "DENIED"
    MODIFIED  = "MODIFIED"
    ESCALATED = "ESCALATED"

PRIORITY_NAME = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}

# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class Plan:
    agent_id:      str
    target:        str           # resource or entity this plan acts on
    action:        str           # what the agent intends to do
    priority:      int  = 2      # 1–4 matching PRIORITY_NAME
    metadata:      dict = field(default_factory=dict)
    plan_id:       str  = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status:        PlanStatus = PlanStatus.PROPOSED
    denial_reason: str = ""

    def label(self) -> str:
        pri = PRIORITY_NAME.get(self.priority, str(self.priority))
        return f"[{self.plan_id}] {self.agent_id} → '{self.action}'  [{pri}]"


@dataclass
class Conflict:
    plan_a:              Plan
    plan_b:              Plan
    conflict_type:       ConflictType
    conflict_id:         str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    resolved:            bool = False
    resolution_strategy: Optional[ResolutionStrategy] = None
    resolution_outcome:  str = ""
    reasoning:           str = ""
    rounds:              int = 0


@dataclass
class Policy:
    policy_id:   str
    name:        str
    description: str
    priority:    int   # higher = evaluated first
    # Returns (approved_plan, denied_plan) if policy applies, else None
    condition: Callable[[Plan, Plan], Optional[Tuple[Plan, Plan]]]


@dataclass
class AuditEntry:
    conflict_id:    str
    conflict_type:  str
    agents:         Tuple[str, str]
    strategy:       str
    outcome:        str
    reasoning:      str
    approved_plans: List[str]
    denied_plans:   List[str]


# ── Agent base + domain specialists ───────────────────────────────────────────

class ConflictingAgent:
    """Submits Plans and responds to mediator decisions."""

    def __init__(self, agent_id: str, role: str, priority: int = 2):
        self.agent_id = agent_id
        self.role     = role
        self.priority = priority
        self.approved: List[Plan] = []
        self.denied:   List[Plan] = []

    def propose(self, target: str, action: str, **metadata) -> Plan:
        return Plan(agent_id=self.agent_id, target=target, action=action,
                    priority=self.priority, metadata=dict(metadata))

    def on_approved(self, plan: Plan):  self.approved.append(plan)
    def on_denied(self,   plan: Plan):  self.denied.append(plan)
    def on_modified(self, plan: Plan, new_action: str):
        plan.action = new_action
        plan.status = PlanStatus.MODIFIED
        self.approved.append(plan)

    def propose_counter(self, blocked_action: str, round_num: int) -> Optional[str]:
        """Return a compromise action string, or None if the agent is rigid."""
        return None  # default: rigid


# Loan processing
class ThroughputAgent(ConflictingAgent):
    def __init__(self): super().__init__("ThroughputAgent", "THROUGHPUT", priority=2)

class FairnessAgent(ConflictingAgent):
    def __init__(self): super().__init__("FairnessAgent",   "COMPLIANCE",  priority=3)

# Manufacturing
class ManufacturingAgentA(ConflictingAgent):
    def __init__(self): super().__init__("ManufacturingAgent_A", "MANUFACTURING", priority=3)

class ManufacturingAgentB(ConflictingAgent):
    def __init__(self): super().__init__("ManufacturingAgent_B", "MANUFACTURING", priority=2)

# Financial trading — both equal priority; BearAgent negotiates
class TradeAgentBull(ConflictingAgent):
    def __init__(self): super().__init__("BullAgent", "TRADING", priority=2)

class TradeAgentBear(ConflictingAgent):
    def __init__(self): super().__init__("BearAgent", "TRADING", priority=2)
    def propose_counter(self, blocked_action: str, round_num: int) -> Optional[str]:
        if round_num == 1: return "SELL_REDUCED_POSITION"   # still SELL-type → conflicts
        if round_num == 2: return "HEDGE_WITH_OPTIONS"      # neutral → accepted
        return None

# Cloud compute
class MLTrainerAgent(ConflictingAgent):
    def __init__(self): super().__init__("MLTrainerAgent", "ML_OPS",  priority=3)

class InferenceAgent(ConflictingAgent):
    def __init__(self): super().__init__("InferenceAgent", "SERVING", priority=2)


# ── SupervisorAgent ────────────────────────────────────────────────────────────

class SupervisorAgent:
    MAX_NEGOTIATION_ROUNDS = 4

    def __init__(self, name: str = "SupervisorAgent"):
        self.name            = name
        self._active_plans:  Dict[str, Plan]           = {}
        self._conflicts:     List[Conflict]             = []
        self._audit:         List[AuditEntry]           = []
        self._policies:      List[Policy]               = []
        self._agents:        Dict[str, ConflictingAgent] = {}
        self._escalated:     List[Conflict]             = []

    def register_agent(self, *agents: ConflictingAgent):
        for a in agents:
            self._agents[a.agent_id] = a

    def add_policy(self, policy: Policy):
        self._policies.append(policy)
        self._policies.sort(key=lambda p: -p.priority)

    # ── Plan ingestion ──────────────────────────────────────────────────────

    def submit_plan(self, plan: Plan,
                    strategy: ResolutionStrategy = ResolutionStrategy.POLICY_BASED):
        conflict = self._detect_conflict(plan)
        if conflict is None:
            self._approve(plan, "No conflict — granted immediately.")
            self._active_plans[plan.target] = plan
            print(f"  ✅ GRANTED   {plan.label()}")
            return

        print(f"\n  ⚡ CONFLICT   [{conflict.conflict_type.value}]  target='{plan.target}'")
        print(f"     Existing : {conflict.plan_a.label()}")
        print(f"     Incoming : {conflict.plan_b.label()}")

        self._conflicts.append(conflict)
        self._resolve(conflict, strategy)

    def clear_target(self, target: str):
        """Release a target so a new plan can claim it (call when a task completes)."""
        self._active_plans.pop(target, None)

    # ── Conflict detection ──────────────────────────────────────────────────

    def _detect_conflict(self, incoming: Plan) -> Optional[Conflict]:
        existing = self._active_plans.get(incoming.target)
        if existing is None or existing.status == PlanStatus.DENIED:
            return None

        # Exclusive resource: both agents claim sole access
        if existing.metadata.get("exclusive") or incoming.metadata.get("exclusive"):
            if existing.agent_id != incoming.agent_id:
                return Conflict(existing, incoming, ConflictType.RESOURCE)

        # Same target, different action → goal conflict
        if existing.action != incoming.action:
            return Conflict(existing, incoming, ConflictType.GOAL)

        return None

    # ── Resolution dispatcher ───────────────────────────────────────────────

    def _resolve(self, conflict: Conflict, strategy: ResolutionStrategy):
        conflict.resolution_strategy = strategy
        dispatch = {
            ResolutionStrategy.HIERARCHICAL:   self._hierarchical_resolve,
            ResolutionStrategy.POLICY_BASED:   self._policy_resolve,
            ResolutionStrategy.NEGOTIATION:    self._negotiation_resolve,
            ResolutionStrategy.GAME_THEORETIC: self._game_theoretic_resolve,
        }
        dispatch[strategy](conflict)

    # ── 1. Hierarchical ─────────────────────────────────────────────────────

    def _hierarchical_resolve(self, conflict: Conflict):
        a, b = conflict.plan_a, conflict.plan_b
        print(f"\n  🏛  HIERARCHICAL RESOLUTION")
        winner, loser = (a, b) if a.priority >= b.priority else (b, a)
        pn = PRIORITY_NAME.get
        reasoning = (
            f"{winner.agent_id} (priority={winner.priority}/{pn(winner.priority,'?')}) "
            f"outranks {loser.agent_id} (priority={loser.priority}/{pn(loser.priority,'?')})."
        )
        print(f"     ✅ APPROVED  {winner.label()}")
        print(f"     ✗  DENIED   {loser.label()}")
        print(f"     Reason: {reasoning}")
        self._approve(winner, reasoning)
        self._deny(loser, reasoning)
        self._active_plans[winner.target] = winner
        conflict.resolved = True
        conflict.resolution_outcome = "APPROVED_A" if winner is a else "APPROVED_B"
        conflict.reasoning = reasoning
        self._record_audit(conflict)

    # ── 2. Policy-based ─────────────────────────────────────────────────────

    def _policy_resolve(self, conflict: Conflict):
        a, b = conflict.plan_a, conflict.plan_b
        print(f"\n  📋 POLICY-BASED RESOLUTION  ({len(self._policies)} polic{'y' if len(self._policies)==1 else 'ies'})")
        for policy in self._policies:
            result = policy.condition(a, b)
            if result is not None:
                approved, denied = result
                reasoning = (f"Policy [{policy.policy_id}] '{policy.name}': "
                             f"{policy.description}")
                print(f"     Policy matched : {policy.name}")
                print(f"     ✅ APPROVED     {approved.label()}")
                print(f"     ✗  DENIED      {denied.label()}")
                print(f"     Reason: {reasoning}")
                self._approve(approved, reasoning)
                self._deny(denied, f"Overridden by policy '{policy.name}'.")
                self._active_plans[approved.target] = approved
                conflict.resolved = True
                conflict.resolution_outcome = "APPROVED_A" if approved is a else "APPROVED_B"
                conflict.reasoning = reasoning
                self._record_audit(conflict)
                return

        print(f"     ⚠  No policy matched — falling back to hierarchical")
        self._hierarchical_resolve(conflict)

    # ── 3. Negotiation ──────────────────────────────────────────────────────

    def _negotiation_resolve(self, conflict: Conflict):
        a, b = conflict.plan_a, conflict.plan_b
        print(f"\n  🤝 NEGOTIATION RESOLUTION")

        # Higher-priority plan holds its slot; the other negotiates
        fixed, flex_plan = (a, b) if a.priority >= b.priority else (b, a)
        flex_agent = self._agents.get(flex_plan.agent_id)

        print(f"     {fixed.agent_id} holds slot (priority={fixed.priority})")
        print(f"     Asking {flex_plan.agent_id} to propose alternatives...")

        for rnd in range(1, self.MAX_NEGOTIATION_ROUNDS + 1):
            conflict.rounds += 1

            counter = None
            if USE_LLM:
                counter = self._llm_counter(flex_plan, rnd)
            if counter is None and flex_agent:
                counter = flex_agent.propose_counter(flex_plan.action, rnd)

            if counter is None:
                print(f"     ✗  Round {rnd}: {flex_plan.agent_id} cannot concede → escalating")
                self._escalate(conflict)
                return

            still_conflicts = self._actions_still_conflict(counter, fixed.action)
            verdict = "⚡ still conflicts" if still_conflicts else "✅ accepted"
            print(f"     ↩  Round {rnd}: '{counter}'  — {verdict}")

            if not still_conflicts:
                reasoning = (
                    f"{fixed.agent_id} retains '{fixed.action}'; "
                    f"{flex_plan.agent_id} modified to '{counter}' "
                    f"after {rnd} round(s)."
                )
                if flex_agent:
                    flex_agent.on_modified(flex_plan, counter)
                self._approve(fixed, reasoning)
                self._active_plans[fixed.target] = fixed
                conflict.resolved = True
                conflict.resolution_outcome = "MODIFIED_BOTH"
                conflict.reasoning = reasoning
                self._record_audit(conflict)
                return

        print(f"     ☠  Max rounds ({self.MAX_NEGOTIATION_ROUNDS}) exhausted → escalating")
        self._escalate(conflict)

    def _actions_still_conflict(self, action_a: str, action_b: str) -> bool:
        """Heuristic: opposing-direction financial/resource actions still conflict."""
        sell_kws = {"SELL", "SHORT", "DUMP", "LIQUIDATE"}
        buy_kws  = {"BUY",  "LONG",  "ACQUIRE", "ACCUMULATE"}
        a_upper, b_upper = action_a.upper(), action_b.upper()
        a_sell = any(k in a_upper for k in sell_kws)
        b_sell = any(k in b_upper for k in sell_kws)
        a_buy  = any(k in a_upper for k in buy_kws)
        b_buy  = any(k in b_upper for k in buy_kws)
        return (a_sell and b_buy) or (a_buy and b_sell)

    # ── 4. Game-theoretic ───────────────────────────────────────────────────

    def _game_theoretic_resolve(self, conflict: Conflict):
        a, b = conflict.plan_a, conflict.plan_b
        print(f"\n  🎮 GAME-THEORETIC RESOLUTION")

        payoffs: Optional[dict] = (conflict.plan_a.metadata.get("payoff_matrix") or
                                   conflict.plan_b.metadata.get("payoff_matrix"))
        if payoffs is None:
            print(f"     ⚠  No payoff_matrix in metadata — falling back to hierarchical")
            self._hierarchical_resolve(conflict)
            return

        strategies_a = list(payoffs.keys())
        strategies_b = list(payoffs[strategies_a[0]].keys())
        col_w = max(len(s) for s in strategies_b) + 6

        print(f"     Payoff matrix  ({a.agent_id} rows  ×  {b.agent_id} cols):")
        print(f"     {'':22s}" + "".join(f"{s:>{col_w}s}" for s in strategies_b))
        print(f"     {'':22s}" + "-" * (col_w * len(strategies_b)))
        for sa in strategies_a:
            cells = "".join(
                f"({'%+d'%payoffs[sa][sb][0]},{'%+d'%payoffs[sa][sb][1]}){'':<{col_w-9}s}"
                for sb in strategies_b
            )
            print(f"     {sa:22s}  {cells}")

        # Find pure-strategy Nash equilibria
        nash: List[Tuple[str, str, int, int]] = []
        for sa in strategies_a:
            for sb in strategies_b:
                pa, pb = payoffs[sa][sb]
                a_can_improve = any(payoffs[sa2][sb][0] > pa for sa2 in strategies_a if sa2 != sa)
                b_can_improve = any(payoffs[sa][sb2][1] > pb for sb2 in strategies_b if sb2 != sb)
                if not a_can_improve and not b_can_improve:
                    nash.append((sa, sb, pa, pb))

        if not nash:
            print(f"     ⚠  No pure-strategy Nash equilibrium found — escalating")
            self._escalate(conflict)
            return

        # Pick Nash with highest combined payoff
        best_sa, best_sb, pa, pb = max(nash, key=lambda x: x[2] + x[3])
        reasoning = (
            f"Nash equilibrium at ({best_sa}, {best_sb}) — combined payoff {pa+pb:+d} "
            f"({a.agent_id}={pa:+d}, {b.agent_id}={pb:+d}). "
            f"Neither agent improves by deviating unilaterally."
        )
        print(f"\n     Nash equilibrium : {a.agent_id}→{best_sa},  {b.agent_id}→{best_sb}")
        print(f"     Payoffs          : ({pa:+d}, {pb:+d})  combined={pa+pb:+d}")
        print(f"     ✅ {a.agent_id} assigned: {best_sa}")
        print(f"     ✅ {b.agent_id} assigned: {best_sb}")

        a.action = best_sa
        b.action = best_sb
        a.status = b.status = PlanStatus.MODIFIED
        self._active_plans[a.target] = a
        for agent_id, new_action in ((a.agent_id, best_sa), (b.agent_id, best_sb)):
            ag = self._agents.get(agent_id)
            if ag:
                ag.approved.append(conflict.plan_a if agent_id == a.agent_id else conflict.plan_b)

        conflict.resolved = True
        conflict.resolution_outcome = "MODIFIED_BOTH"
        conflict.reasoning = reasoning
        self._record_audit(conflict)

    # ── LLM path (negotiation) ───────────────────────────────────────────────

    def _llm_counter(self, plan: Plan, round_num: int) -> Optional[str]:
        try:
            import anthropic
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model="claude-opus-4-5", max_tokens=200,
                tools=[{
                    "name": "propose_alternative",
                    "description": "Propose a compromise action to resolve the conflict",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "alternative_action": {
                                "type": "string",
                                "description": "Short UPPER_SNAKE_CASE action string"
                            },
                            "reasoning": {"type": "string"}
                        },
                        "required": ["alternative_action", "reasoning"]
                    }
                }],
                messages=[{"role": "user", "content": (
                    f"Agent {plan.agent_id} wants to '{plan.action}' on '{plan.target}' "
                    f"but it conflicts. Negotiation round {round_num}. "
                    f"Propose a reasonable UPPER_SNAKE_CASE compromise action."
                )}]
            )
            for block in resp.content:
                if block.type == "tool_use" and block.name == "propose_alternative":
                    return block.input.get("alternative_action")
        except Exception:
            pass
        return None

    # ── State helpers ────────────────────────────────────────────────────────

    def _approve(self, plan: Plan, reasoning: str = ""):
        plan.status = PlanStatus.APPROVED
        agent = self._agents.get(plan.agent_id)
        if agent:
            agent.on_approved(plan)

    def _deny(self, plan: Plan, reason: str = ""):
        plan.status = PlanStatus.DENIED
        plan.denial_reason = reason
        agent = self._agents.get(plan.agent_id)
        if agent:
            agent.on_denied(plan)

    def _escalate(self, conflict: Conflict):
        conflict.resolution_outcome = "ESCALATED"
        conflict.reasoning = "Automated resolution failed — human operator review required."
        conflict.plan_a.status = PlanStatus.ESCALATED
        conflict.plan_b.status = PlanStatus.ESCALATED
        self._escalated.append(conflict)
        print(f"     ⚠  ESCALATED — both plans held pending human review")
        self._record_audit(conflict)

    def _record_audit(self, conflict: Conflict):
        self._audit.append(AuditEntry(
            conflict_id=conflict.conflict_id,
            conflict_type=conflict.conflict_type.value,
            agents=(conflict.plan_a.agent_id, conflict.plan_b.agent_id),
            strategy=(conflict.resolution_strategy.value
                      if conflict.resolution_strategy else "NONE"),
            outcome=conflict.resolution_outcome,
            reasoning=conflict.reasoning,
            approved_plans=[p.plan_id for p in (conflict.plan_a, conflict.plan_b)
                            if p.status in (PlanStatus.APPROVED, PlanStatus.MODIFIED)],
            denied_plans=[p.plan_id for p in (conflict.plan_a, conflict.plan_b)
                          if p.status == PlanStatus.DENIED],
        ))

    # ── Audit trail ─────────────────────────────────────────────────────────

    def print_audit_trail(self):
        print("\n" + "═" * 66)
        print(f"  AUDIT TRAIL  —  {self.name}")
        print("═" * 66)
        if not self._audit:
            print("  (no conflicts recorded)\n")
            return
        for i, e in enumerate(self._audit, 1):
            print(f"\n  [{i}] Conflict {e.conflict_id}  [{e.conflict_type}]")
            print(f"      Agents    : {e.agents[0]} ↔ {e.agents[1]}")
            print(f"      Strategy  : {e.strategy}")
            print(f"      Outcome   : {e.outcome}")
            print(f"      Reasoning : {e.reasoning}")
            if e.approved_plans:
                print(f"      Approved  : {', '.join(e.approved_plans)}")
            if e.denied_plans:
                print(f"      Denied    : {', '.join(e.denied_plans)}")
        if self._escalated:
            print(f"\n  ⚠  {len(self._escalated)} conflict(s) escalated to human operator")
        print()


# ── Demo helpers ───────────────────────────────────────────────────────────────

def _hdr(title: str, subtitle: str = ""):
    print("\n" + "═" * 66)
    print(f"  {title}")
    print("═" * 66)
    if subtitle:
        print(f"  {subtitle}\n")


# ══ DEMO 1 — Policy-Based: Loan Processing (from book) ════════════════════════

def demo1_policy_loan_processing():
    _hdr(
        "DEMO 1 — Policy-Based: Loan Processing",
        "ThroughputAgent (ADVANCE) vs FairnessAgent (HOLD).\n"
        "  Compliance policy overrides speed KPI — fairness agent always wins."
    )

    supervisor = SupervisorAgent("LoanProcessingSupervisor")
    throughput = ThroughputAgent()
    fairness   = FairnessAgent()
    supervisor.register_agent(throughput, fairness)

    # POL-001: any plan holding a batch for fairness review has priority over advancement
    def fairness_policy(a: Plan, b: Plan) -> Optional[Tuple[Plan, Plan]]:
        for plan in (a, b):
            if plan.action == "HOLD_FOR_FAIRNESS_REVIEW":
                other = b if plan is a else a
                return (plan, other)   # fairness plan approved, other denied
        return None

    supervisor.add_policy(Policy(
        policy_id="POL-001",
        name="FAIRNESS_CHECK_REQUIRED",
        description=(
            "All batches must receive FAIRNESS_PASSED status before advancing to approval. "
            "Compliance and ethical guidelines override speed KPIs."
        ),
        priority=10,
        condition=fairness_policy,
    ))

    print("  Phase 1 — Agents submit competing plans for Loan Batch #LB-2024-047")
    p_thru  = throughput.propose("LoanBatch-LB-2024-047", "ADVANCE_TO_APPROVAL")
    p_fair  = fairness.propose("LoanBatch-LB-2024-047",   "HOLD_FOR_FAIRNESS_REVIEW")

    supervisor.submit_plan(p_thru, ResolutionStrategy.POLICY_BASED)
    supervisor.submit_plan(p_fair, ResolutionStrategy.POLICY_BASED)

    print("\n  Phase 2 — Fairness check completes (20 min later). ThroughputAgent resubmits.")
    supervisor.clear_target("LoanBatch-LB-2024-047")
    p_thru2 = throughput.propose("LoanBatch-LB-2024-047", "ADVANCE_TO_APPROVAL")
    supervisor.submit_plan(p_thru2, ResolutionStrategy.POLICY_BASED)
    print("  → Batch LB-2024-047 cleared for final approval.\n")

    supervisor.print_audit_trail()


# ══ DEMO 2 — Hierarchical: Manufacturing Robot Arm Workspace ══════════════════

def demo2_hierarchical_robot_arm():
    _hdr(
        "DEMO 2 — Hierarchical: Robot Arm Workspace",
        "Two manufacturing agents claim WorkZone-B simultaneously.\n"
        "  Higher-priority arm (Agent_A, HIGH) wins; lower-priority (Agent_B, MEDIUM) waits."
    )

    supervisor = SupervisorAgent("ManufacturingSupervisor")
    agent_a = ManufacturingAgentA()
    agent_b = ManufacturingAgentB()
    supervisor.register_agent(agent_a, agent_b)

    p_a = agent_a.propose("WorkZone-B", "EXTEND_ARM_GRASP_COMPONENT",
                          safety_critical=True, duration_ms=1500)
    p_b = agent_b.propose("WorkZone-B", "ROTATE_TOOL_APPLY_TORQUE",
                          safety_critical=True, duration_ms=800)

    supervisor.submit_plan(p_a, ResolutionStrategy.HIERARCHICAL)
    supervisor.submit_plan(p_b, ResolutionStrategy.HIERARCHICAL)

    supervisor.print_audit_trail()


# ══ DEMO 3 — Negotiation: Financial Trading Conflict ═════════════════════════

def demo3_negotiation_trading():
    _hdr(
        "DEMO 3 — Negotiation: Financial Trading Conflict",
        "BullAgent (BUY_LARGE) vs BearAgent (SELL_SHORT) on AAPL.\n"
        "  Round 1: SELL_REDUCED still conflicts. Round 2: HEDGE_WITH_OPTIONS → accepted."
    )

    supervisor = SupervisorAgent("TradingSupervisor")
    bull = TradeAgentBull()
    bear = TradeAgentBear()
    supervisor.register_agent(bull, bear)

    p_bull = bull.propose("AAPL", "BUY_LARGE_POSITION",
                          rationale="Strong earnings beat; upward momentum confirmed")
    p_bear = bear.propose("AAPL", "SELL_SHORT_LARGE",
                          rationale="Overvalued vs sector peers; correction expected")

    supervisor.submit_plan(p_bull, ResolutionStrategy.NEGOTIATION)
    supervisor.submit_plan(p_bear, ResolutionStrategy.NEGOTIATION)

    supervisor.print_audit_trail()


# ══ DEMO 4 — Game-Theoretic: Cloud GPU Cluster ════════════════════════════════

def demo4_game_theoretic_cloud():
    _hdr(
        "DEMO 4 — Game-Theoretic: Cloud GPU Cluster",
        "MLTrainerAgent and InferenceAgent both claim exclusive GPU access.\n"
        "  Nash equilibrium at (SHARE_FAIRLY, SHARE_FAIRLY) → both agents assigned."
    )

    # Payoff matrix: DEMAND_ALL vs SHARE_FAIRLY
    #   Both DEMAND_ALL → GPU contention, OOM errors, both stall   (-5,-5)
    #   A demands, B shares → A gets full throughput, B degraded    (+3,+1)
    #   Both share → both run well, cluster 100% utilised           (+4,+4)
    #
    # Nash check at (SHARE_FAIRLY, SHARE_FAIRLY):
    #   A deviates to DEMAND_ALL → gets +3 vs +4 → A cannot improve ✓
    #   B deviates to DEMAND_ALL → gets +3 vs +4 → B cannot improve ✓
    #   → (SHARE_FAIRLY, SHARE_FAIRLY) is the unique Nash equilibrium.
    payoff_matrix = {
        "DEMAND_ALL": {
            "DEMAND_ALL":   (-5, -5),
            "SHARE_FAIRLY": (+3, +1),
        },
        "SHARE_FAIRLY": {
            "DEMAND_ALL":   (+1, +3),
            "SHARE_FAIRLY": (+4, +4),
        },
    }

    supervisor = SupervisorAgent("CloudSupervisor")
    ml_agent  = MLTrainerAgent()
    inf_agent = InferenceAgent()
    supervisor.register_agent(ml_agent, inf_agent)

    p_ml  = ml_agent.propose(
        "GPU-Cluster-1", "DEMAND_ALL_RESOURCES",
        exclusive=True, payoff_matrix=payoff_matrix,
        job="transformer_training_v4"
    )
    p_inf = inf_agent.propose(
        "GPU-Cluster-1", "DEMAND_ALL_RESOURCES",
        exclusive=True,
        job="realtime_inference_service"
    )

    supervisor.submit_plan(p_ml,  ResolutionStrategy.GAME_THEORETIC)
    supervisor.submit_plan(p_inf, ResolutionStrategy.GAME_THEORETIC)

    supervisor.print_audit_trail()


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("═" * 66)
    print("  CONFLICT RESOLUTION PATTERN — Enterprise & Industrial Scenarios")
    print("═" * 66)
    if not USE_LLM:
        print("\n  DEMO MODE — mock resolution (set ANTHROPIC_API_KEY for real LLM)\n")

    demo1_policy_loan_processing()
    demo2_hierarchical_robot_arm()
    demo3_negotiation_trading()
    demo4_game_theoretic_cloud()

    print("═" * 66)
    print("  Key Takeaways")
    print("═" * 66)
    print()
    print("  1. Policy-Based    — deterministic, auditable, compliance-first;"
          " externalises logic so humans can inspect and modify it")
    print("  2. Hierarchical    — fast and decisive; best when clear authority chains exist")
    print("  3. Negotiation     — win-win where agents have flexibility;"
          " escalates only when rigid")
    print("  4. Game-Theoretic  — aligns self-interest with global optimum via Nash eq.;"
          " computationally intensive but principled")
    print()
