"""
Contract-Net Marketplace Pattern — Cloud ML Training Provider Selection
-----------------------------------------------------------------------
Demonstrates:
  1. Task announcement broadcast with constraints (max_cost, max_eta, min_confidence)
  2. Bidder agents that self-evaluate and submit (cost, ETA, confidence) bids
  3. Bid refusal — agents decline when they can't meet constraints
  4. Utility function — weighted scoring of competing bids
  5. Reputation system — agents penalized for overpromising
  6. Dynamic availability — agents go offline between rounds
  7. Bid deadline enforcement — solicitor stops waiting after N seconds
  8. NoBidsException — handled gracefully when no agent can fulfill

Scenario: A data science team needs to train ML models with varying
constraints (some budget-limited, some deadline-critical, some quality-critical).
The solicitor finds the best cloud/on-prem provider for each job at runtime.
"""

import time
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Literal
from enum import Enum


# ─────────────────────────────────────────────────────────────
# 1. TASK & BID MODELS
# ─────────────────────────────────────────────────────────────

TaskType = Literal["train_model", "fine_tune", "batch_inference", "data_processing"]


@dataclass
class TaskAnnouncement:
    task_id:        str
    task_type:      TaskType
    description:    str
    # Constraints — bidders must respect these or refuse
    max_cost:       Optional[float] = None   # USD ceiling
    max_eta_hours:  Optional[float] = None   # time ceiling
    min_confidence: Optional[float] = None   # quality floor
    # Payload — determines how hard the task is
    model_size_b:   float = 1.0              # billions of parameters
    dataset_gb:     float = 10.0
    # Utility weights — how the solicitor prioritises competing bids
    weight_cost:       float = 0.4
    weight_eta:        float = 0.3
    weight_confidence: float = 0.3


@dataclass
class Bid:
    agent_id:    str
    task_id:     str
    cost:        float          # USD
    eta_hours:   float          # estimated completion time
    confidence:  float          # 0.0 – 1.0 self-assessed quality score
    hardware:    str            # what it will run on
    notes:       str = ""


class NoBidsException(Exception):
    pass


# ─────────────────────────────────────────────────────────────
# 2. REPUTATION TRACKER
#    Agents that overbid confidence get penalised in future rounds.
#    Reputation multiplies the agent's utility score.
# ─────────────────────────────────────────────────────────────

class ReputationTracker:

    def __init__(self):
        self._scores: dict[str, list[float]] = {}   # agent_id → list of deltas

    def record_outcome(self, agent_id: str, promised_confidence: float,
                       actual_quality: float):
        """Actual quality is measured post-execution (0.0–1.0)."""
        delta = actual_quality - promised_confidence  # negative = overpromised
        self._scores.setdefault(agent_id, []).append(delta)

    def get_reputation(self, agent_id: str) -> float:
        """
        Returns a multiplier applied to the agent's utility score.
        1.0 = neutral, >1.0 = good track record, <1.0 = overpromised historically.
        Range: 0.5 – 1.2
        """
        history = self._scores.get(agent_id, [])
        if not history:
            return 1.0
        avg_delta = sum(history) / len(history)
        return max(0.5, min(1.2, 1.0 + avg_delta))

    def summary(self) -> dict:
        return {
            agent: f"{self.get_reputation(agent):.2f}x"
            for agent in self._scores
        }


# ─────────────────────────────────────────────────────────────
# 3. BIDDER AGENTS — Each represents a different provider
#    Each knows its own cost structure, hardware limits, specialties.
# ─────────────────────────────────────────────────────────────

class BidderAgent:
    """Base class. Subclasses define provider-specific pricing and capabilities."""

    # Subclasses set these
    agent_id:       str
    hardware:       str
    cost_per_gb:    float   # USD per GB of data
    cost_per_b:     float   # USD per billion parameters
    speed_factor:   float   # lower = faster (1.0 is baseline)
    base_confidence: float  # inherent quality ceiling
    online:         bool = True

    def receive_announcement(self, task: TaskAnnouncement) -> Optional[Bid]:
        if not self.online:
            return None  # agent is offline — silent refusal

        cost = self._estimate_cost(task)
        eta  = self._estimate_eta(task)
        conf = self._assess_confidence(task)

        # Hard refusal if task violates constraints
        if task.max_cost       and cost > task.max_cost:
            print(f"    [{self.agent_id}] Refusing — cost ${cost:.0f} exceeds max ${task.max_cost:.0f}")
            return None
        if task.max_eta_hours  and eta > task.max_eta_hours:
            print(f"    [{self.agent_id}] Refusing — ETA {eta:.1f}h exceeds max {task.max_eta_hours:.1f}h")
            return None
        if task.min_confidence and conf < task.min_confidence:
            print(f"    [{self.agent_id}] Refusing — confidence {conf:.0%} below min {task.min_confidence:.0%}")
            return None

        return Bid(
            agent_id   = self.agent_id,
            task_id    = task.task_id,
            cost       = round(cost, 2),
            eta_hours  = round(eta, 2),
            confidence = round(conf, 3),
            hardware   = self.hardware,
            notes      = self._notes(task, cost, eta, conf)
        )

    def execute_contract(self, task: TaskAnnouncement, bid: Bid) -> dict:
        """Simulate execution. Returns actual quality (may differ from bid confidence)."""
        # Add realistic variance — agents sometimes underdeliver
        variance = random.uniform(-0.05, 0.03)
        actual_quality = max(0.0, min(1.0, bid.confidence + variance))
        return {
            "status":           "success",
            "actual_quality":   round(actual_quality, 3),
            "actual_cost":      round(bid.cost * random.uniform(0.95, 1.05), 2),
            "actual_eta_hours": round(bid.eta_hours * random.uniform(0.9, 1.1), 2),
        }

    def _estimate_cost(self, task: TaskAnnouncement) -> float:
        return (task.model_size_b * self.cost_per_b) + (task.dataset_gb * self.cost_per_gb)

    def _estimate_eta(self, task: TaskAnnouncement) -> float:
        base_hours = (task.model_size_b * 0.5) + (task.dataset_gb * 0.02)
        return base_hours * self.speed_factor

    def _assess_confidence(self, task: TaskAnnouncement) -> float:
        return self.base_confidence

    def _notes(self, task, cost, eta, conf) -> str:
        return f"{self.hardware} | ${cost:.0f} | {eta:.1f}h | {conf:.0%} confidence"


class AWSAgent(BidderAgent):
    agent_id       = "AWS-SageMaker"
    hardware       = "p4d.24xlarge (8×A100)"
    cost_per_b     = 12.0
    cost_per_gb    = 0.8
    speed_factor   = 0.7     # fast
    base_confidence = 0.88

    def _assess_confidence(self, task):
        # AWS is especially strong on large models
        boost = 0.04 if task.model_size_b >= 7 else 0.0
        return min(0.95, self.base_confidence + boost)


class AzureAgent(BidderAgent):
    agent_id       = "Azure-ML"
    hardware       = "Standard_ND96asr (8×A100)"
    cost_per_b     = 10.5
    cost_per_gb    = 0.7
    speed_factor   = 0.85
    base_confidence = 0.86

    def _assess_confidence(self, task):
        # Azure strong on fine-tuning
        boost = 0.05 if task.task_type == "fine_tune" else 0.0
        return min(0.95, self.base_confidence + boost)


class GCPAgent(BidderAgent):
    agent_id       = "GCP-Vertex"
    hardware       = "a2-megagpu-16g (16×A100)"
    cost_per_b     = 9.0
    cost_per_gb    = 0.65
    speed_factor   = 0.75
    base_confidence = 0.85

    def _assess_confidence(self, task):
        # GCP strong on large batch jobs
        boost = 0.04 if task.task_type == "batch_inference" else 0.0
        return min(0.95, self.base_confidence + boost)


class OnPremAgent(BidderAgent):
    agent_id       = "OnPrem-Cluster"
    hardware       = "8×RTX 4090 (local)"
    cost_per_b     = 2.5      # much cheaper — sunk cost hardware
    cost_per_gb    = 0.1
    speed_factor   = 2.8      # slow — older hardware, no auto-scaling
    base_confidence = 0.78

    def _estimate_cost(self, task):
        # OnPrem cost is mainly electricity + ops overhead
        base = super()._estimate_cost(task)
        # Can't handle very large models
        if task.model_size_b > 13:
            return float("inf")  # will trigger refusal
        return base


class SpotInstanceAgent(BidderAgent):
    """Uses preemptible/spot instances — cheap but uncertain ETA."""
    agent_id       = "AWS-Spot"
    hardware       = "p3.16xlarge Spot (8×V100)"
    cost_per_b     = 4.0      # ~70% cheaper than on-demand
    cost_per_gb    = 0.3
    speed_factor   = 1.1
    base_confidence = 0.72    # lower — spot can be preempted

    def _assess_confidence(self, task):
        # Spot unreliable for long jobs
        penalty = 0.1 if self._estimate_eta(task) > 6 else 0.0
        return max(0.5, self.base_confidence - penalty)


# ─────────────────────────────────────────────────────────────
# 4. SOLICITOR — Manages the auction lifecycle
# ─────────────────────────────────────────────────────────────

class Solicitor:

    BID_TIMEOUT_SECONDS = 2.0   # real systems: 30–60s

    def __init__(self, bidders: list[BidderAgent],
                 reputation: ReputationTracker):
        self.bidders    = bidders
        self.reputation = reputation

    def request_task_fulfillment(self, task: TaskAnnouncement) -> dict:
        print(f"\n{'='*60}")
        print(f"  [Solicitor] Task: {task.description}")
        print(f"  Constraints: cost≤${task.max_cost or '∞'} | "
              f"ETA≤{task.max_eta_hours or '∞'}h | "
              f"conf≥{task.min_confidence or 0:.0%}")
        print(f"  Weights: cost={task.weight_cost} | "
              f"eta={task.weight_eta} | conf={task.weight_confidence}")
        print(f"{'='*60}")

        # Step 1: Broadcast and collect bids (with timeout)
        bids = self._broadcast_and_collect(task)

        if not bids:
            raise NoBidsException(
                f"No agent could fulfill task '{task.task_id}'. "
                f"Consider relaxing constraints."
            )

        # Step 2: Score bids using utility function (with reputation)
        print(f"\n  [Solicitor] Scoring {len(bids)} bid(s)...")
        scored = self._score_bids(bids, task)
        for bid, score in scored:
            rep = self.reputation.get_reputation(bid.agent_id)
            print(f"    {bid.agent_id:22s} utility={score:.4f} "
                  f"(rep={rep:.2f}x) | {bid.notes}")

        # Step 3: Award to highest utility
        winning_bid, winning_score = scored[0]
        print(f"\n  [Solicitor] AWARDED → {winning_bid.agent_id} "
              f"(utility={winning_score:.4f})")

        # Step 4: Execute and record outcome
        agent = next(a for a in self.bidders if a.agent_id == winning_bid.agent_id)
        result = agent.execute_contract(task, winning_bid)
        self.reputation.record_outcome(
            winning_bid.agent_id,
            winning_bid.confidence,
            result["actual_quality"]
        )

        return {
            "task_id":    task.task_id,
            "winner":     winning_bid.agent_id,
            "bid":        winning_bid,
            "result":     result,
        }

    def _broadcast_and_collect(self, task: TaskAnnouncement) -> list[Bid]:
        """Broadcasts to all bidders concurrently. Enforces timeout."""
        print(f"\n  [Solicitor] Broadcasting to {len(self.bidders)} agent(s)...")
        bids = []
        lock = threading.Lock()

        def collect_bid(agent):
            bid = agent.receive_announcement(task)
            if bid:
                with lock:
                    bids.append(bid)
                print(f"    [{agent.agent_id}] Bid received: {bid.notes}")

        threads = [threading.Thread(target=collect_bid, args=(a,)) for a in self.bidders]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=self.BID_TIMEOUT_SECONDS)

        return bids

    def _score_bids(self, bids: list[Bid],
                    task: TaskAnnouncement) -> list[tuple[Bid, float]]:
        """
        Utility function: normalise each dimension to [0,1], apply weights.
        utility = (conf_score * w_conf) + ((1 - cost_score) * w_cost) + ((1 - eta_score) * w_eta)
        Multiplied by reputation factor.
        """
        if len(bids) == 1:
            rep = self.reputation.get_reputation(bids[0].agent_id)
            return [(bids[0], 1.0 * rep)]

        costs = [b.cost       for b in bids]
        etas  = [b.eta_hours  for b in bids]
        confs = [b.confidence for b in bids]

        def normalise(val, vals):
            lo, hi = min(vals), max(vals)
            return (val - lo) / (hi - lo) if hi != lo else 1.0

        scored = []
        for bid in bids:
            cost_score = normalise(bid.cost,       costs)  # higher cost = worse
            eta_score  = normalise(bid.eta_hours,  etas)   # higher ETA  = worse
            conf_score = normalise(bid.confidence, confs)  # higher conf = better

            raw_utility = (
                conf_score             * task.weight_confidence +
                (1 - cost_score)       * task.weight_cost +
                (1 - eta_score)        * task.weight_eta
            )
            rep     = self.reputation.get_reputation(bid.agent_id)
            utility = raw_utility * rep
            scored.append((bid, utility))

        return sorted(scored, key=lambda x: x[1], reverse=True)


# ─────────────────────────────────────────────────────────────
# 5. DEMO — Four scenarios showing dynamic selection
# ─────────────────────────────────────────────────────────────

def print_result(outcome: dict):
    b = outcome["bid"]
    r = outcome["result"]
    print(f"\n  ── Outcome ──────────────────────────────────")
    print(f"  Winner:   {outcome['winner']}")
    print(f"  Promised: ${b.cost:.0f} | {b.eta_hours:.1f}h | {b.confidence:.0%} conf")
    print(f"  Actual:   ${r['actual_cost']:.0f} | "
          f"{r['actual_eta_hours']:.1f}h | {r['actual_quality']:.0%} quality")


if __name__ == "__main__":
    random.seed(42)

    # Initialise agents and reputation tracker
    reputation = ReputationTracker()
    aws   = AWSAgent()
    azure = AzureAgent()
    gcp   = GCPAgent()
    onprem = OnPremAgent()
    spot  = SpotInstanceAgent()
    all_agents = [aws, azure, gcp, onprem, spot]

    solicitor = Solicitor(all_agents, reputation)

    # ── Scenario 1: Budget-constrained ────────────────────────
    # Max $100. OnPrem will win if fast enough — otherwise Spot.
    print("\n\n▶ Scenario 1: Budget-constrained ($100 max, 7B model)")
    task1 = TaskAnnouncement(
        task_id        = "JOB-001",
        task_type      = "train_model",
        description    = "Train a 7B parameter LLM on 50GB dataset (budget: $100)",
        max_cost       = 100,
        model_size_b   = 7.0,
        dataset_gb     = 50.0,
        weight_cost    = 0.6,    # cost is the priority
        weight_eta     = 0.2,
        weight_confidence = 0.2,
    )
    try:
        result1 = solicitor.request_task_fulfillment(task1)
        print_result(result1)
    except NoBidsException as e:
        print(f"\n  [Solicitor] NO BIDS — {e}")

    # ── Scenario 2: Speed-critical ─────────────────────────────
    # Results needed within 3 hours. OnPrem and Spot will be filtered out.
    print("\n\n▶ Scenario 2: Speed-critical (3h deadline, 3B model)")
    task2 = TaskAnnouncement(
        task_id        = "JOB-002",
        task_type      = "fine_tune",
        description    = "Fine-tune 3B model for production deploy (ship today)",
        max_eta_hours  = 3.0,
        model_size_b   = 3.0,
        dataset_gb     = 20.0,
        weight_cost    = 0.2,
        weight_eta     = 0.6,    # speed is the priority
        weight_confidence = 0.2,
    )
    try:
        result2 = solicitor.request_task_fulfillment(task2)
        print_result(result2)
    except NoBidsException as e:
        print(f"\n  [Solicitor] NO BIDS — {e}")

    # ── Scenario 3: Quality-critical ──────────────────────────
    # Need 85%+ confidence. Spot and OnPrem will self-refuse.
    print("\n\n▶ Scenario 3: Quality-critical (min 85% confidence, 13B model)")
    task3 = TaskAnnouncement(
        task_id        = "JOB-003",
        task_type      = "train_model",
        description    = "Train flagship 13B model — must meet accuracy SLA",
        min_confidence = 0.85,
        model_size_b   = 13.0,
        dataset_gb     = 200.0,
        weight_cost    = 0.2,
        weight_eta     = 0.2,
        weight_confidence = 0.6,  # quality is the priority
    )
    try:
        result3 = solicitor.request_task_fulfillment(task3)
        print_result(result3)
    except NoBidsException as e:
        print(f"\n  [Solicitor] NO BIDS — {e}")

    # ── Scenario 4: Reputation effect ─────────────────────────
    # After 3 rounds, reputation scores diverge. Same task as 1 but
    # now reputation multipliers affect the outcome.
    print("\n\n▶ Scenario 4: Reputation effect (same as Scenario 1 — reputation now applies)")
    print(f"  Reputation scores so far: {reputation.summary()}")
    task4 = TaskAnnouncement(
        task_id        = "JOB-004",
        task_type      = "batch_inference",
        description    = "Batch inference on 7B model — repeat of constrained job",
        max_cost       = 100,
        model_size_b   = 7.0,
        dataset_gb     = 50.0,
        weight_cost    = 0.5,
        weight_eta     = 0.25,
        weight_confidence = 0.25,
    )
    try:
        result4 = solicitor.request_task_fulfillment(task4)
        print_result(result4)
    except NoBidsException as e:
        print(f"\n  [Solicitor] NO BIDS — {e}")

    # ── Scenario 5: All agents offline ─────────────────────────
    print("\n\n▶ Scenario 5: All cloud agents offline (only OnPrem available, too slow)")
    aws.online   = False
    azure.online = False
    gcp.online   = False
    spot.online  = False
    task5 = TaskAnnouncement(
        task_id        = "JOB-005",
        task_type      = "train_model",
        description    = "Urgent 20B model training (cloud outage)",
        max_eta_hours  = 4.0,    # OnPrem can't meet this
        model_size_b   = 20.0,   # OnPrem can't handle this size either
        dataset_gb     = 100.0,
    )
    try:
        result5 = solicitor.request_task_fulfillment(task5)
        print_result(result5)
    except NoBidsException as e:
        print(f"\n  [Solicitor] NO BIDS — {e}")

    # Final reputation summary
    print(f"\n{'='*60}")
    print("  FINAL REPUTATION SCORES")
    print(f"{'='*60}")
    for agent_id, score in reputation.summary().items():
        print(f"  {agent_id:22s} → {score}")
