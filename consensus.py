"""
Consensus Pattern — Multi-Round Belief Convergence
----------------------------------------------------
Demonstrates:
  1. ConsensusManager — orchestrates a structured multi-round debate protocol
  2. Iterative adjustment — each agent observes the collective mean and pulls
     its estimate toward it by a configurable learning rate
  3. Convergence detection — process terminates when max - min <= tolerance
  4. Outlier detection — agents whose estimate deviates >2σ from the mean
     are flagged and their weight is reduced in subsequent rounds
  5. ReputationTracker — records each agent's historical accuracy vs final
     consensus; degrades weight of consistently biased agents over time
  6. Full audit trail — every round, every agent estimate, every adjustment
     is logged and printed as a readable debate transcript
  7. Mock mode (no API key) + LLM mode (LLM-generated initial forecasts
     and reasoning)

Scenario: Financial forecasting debate
  OptimistAgent    — skews bullish; focuses on positive market signals
  PessimistAgent   — skews bearish; focuses on downside risks
  RealistAgent     — anchors to historical performance data
  MomentumAgent    — follows recent trend extrapolation
  SentimentAgent   — reads analyst sentiment and social signals

ConsensusManager runs the debate. Agents share forecasts, observe the mean,
and adjust. The round ends when all estimates fall within tolerance, or
max_rounds is exhausted. A MaliciousAgent demo shows outlier detection.
"""

import math
import os
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import anthropic


USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))
client  = anthropic.Anthropic() if USE_LLM else None


# ─────────────────────────────────────────────────────────────
# 1. FORECAST — A single agent's estimate for one round
# ─────────────────────────────────────────────────────────────

@dataclass
class Forecast:
    agent_name:  str
    value:       float
    reasoning:   str
    round_num:   int
    weight:      float = 1.0     # reduced for outliers / low-reputation agents
    is_outlier:  bool  = False


# ─────────────────────────────────────────────────────────────
# 2. ROUND RECORD — Snapshot of one full debate round
# ─────────────────────────────────────────────────────────────

@dataclass
class RoundRecord:
    round_num:    int
    forecasts:    list[Forecast]
    mean:         float
    robust_mean:  float          # mean excluding flagged outliers
    spread:       float          # max - min (honest agents only)
    std_dev:      float
    outliers:     list[str]      # agent names flagged this round
    converged:    bool


# ─────────────────────────────────────────────────────────────
# 3. CONSENSUS RESULT — Final outcome of the debate
# ─────────────────────────────────────────────────────────────

@dataclass
class ConsensusResult:
    goal:         str
    final_value:  float
    converged:    bool
    rounds_taken: int
    rounds:       list[RoundRecord]
    participants: list[str]
    outliers_detected: list[str]


# ─────────────────────────────────────────────────────────────
# 4. REPUTATION TRACKER — Weights agents by historical accuracy
# ─────────────────────────────────────────────────────────────

class ReputationTracker:
    def __init__(self):
        self._history: dict[str, list[float]] = {}   # agent → list of |error|

    def record(self, agent_name: str, estimate: float, final_consensus: float) -> None:
        err = abs(estimate - final_consensus)
        self._history.setdefault(agent_name, []).append(err)

    def weight_for(self, agent_name: str) -> float:
        history = self._history.get(agent_name, [])
        if len(history) < 2:
            return 1.0
        avg_error = statistics.mean(history)
        # Scale: 0 error → weight 1.0, large error → approaches 0.3 floor
        return max(0.3, 1.0 - (avg_error / 50.0))

    def summary(self) -> dict[str, dict]:
        out = {}
        for agent, errors in self._history.items():
            out[agent] = {
                "debates": len(errors),
                "avg_error": round(statistics.mean(errors), 2),
                "weight":    round(self.weight_for(agent), 3),
            }
        return out


# ─────────────────────────────────────────────────────────────
# 5. FORECASTING AGENTS — Each has a distinct analytical bias
# ─────────────────────────────────────────────────────────────

class ForecastingAgent:
    """Base class. Each agent has a name and a bias that shapes its initial
    estimate and how aggressively it adjusts toward the group mean."""

    def __init__(self, name: str, learning_rate: float = 0.4):
        self.name          = name
        self.learning_rate = learning_rate   # 0 = never adjust, 1 = jump to mean

    def initial_forecast(self, goal: str, context: dict) -> Forecast:
        if USE_LLM and client:
            return self._llm_forecast(goal, context, round_num=1)
        return self._mock_initial_forecast(goal, context)

    def adjust_forecast(
        self,
        current: float,
        group_mean: float,
        round_num: int,
        goal: str,
    ) -> Forecast:
        """Pull estimate toward group mean by learning_rate."""
        adjusted = current + self.learning_rate * (group_mean - current)
        return Forecast(
            agent_name=self.name,
            value=round(adjusted, 2),
            reasoning=f"Adjusted {current:.1f} → {adjusted:.1f} (mean={group_mean:.1f}, lr={self.learning_rate})",
            round_num=round_num,
        )

    def _llm_forecast(self, goal: str, context: dict, round_num: int) -> Forecast:
        schema = {
            "name": "submit_forecast",
            "description": "Submit your revenue forecast with reasoning",
            "input_schema": {
                "type": "object",
                "properties": {
                    "value":     {"type": "number", "description": "Forecast value in $M"},
                    "reasoning": {"type": "string", "description": "One sentence justification"},
                },
                "required": ["value", "reasoning"]
            }
        }
        context_str = "\n".join(f"  {k}: {v}" for k, v in context.items())
        resp = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=256,
            tools=[schema],
            tool_choice={"type": "tool", "name": "submit_forecast"},
            messages=[{
                "role": "user",
                "content": (
                    f"You are {self.name}. {self._persona()}\n\n"
                    f"Goal: {goal}\nContext:\n{context_str}\n\n"
                    f"Submit your revenue forecast in $M."
                )
            }]
        )
        for block in resp.content:
            if block.type == "tool_use":
                return Forecast(
                    agent_name=self.name,
                    value=float(block.input["value"]),
                    reasoning=block.input["reasoning"],
                    round_num=round_num,
                )
        return self._mock_initial_forecast(goal, context)

    def _persona(self) -> str:
        return "You provide balanced financial forecasts."

    def _mock_initial_forecast(self, goal: str, context: dict) -> Forecast:
        raise NotImplementedError


class OptimistAgent(ForecastingAgent):
    def __init__(self):
        super().__init__("OptimistAgent", learning_rate=0.35)

    def _persona(self) -> str:
        return "You focus on positive market trends, strong demand signals, and upside scenarios."

    def _mock_initial_forecast(self, goal: str, context: dict) -> Forecast:
        base = context.get("last_quarter_revenue", 100)
        value = round(base * 1.10 + 5, 1)     # bullish: +10% + bonus
        return Forecast(self.name, value,
                        "Strong demand signals and positive macro tailwinds suggest above-trend growth.",
                        round_num=1)


class PessimistAgent(ForecastingAgent):
    def __init__(self):
        super().__init__("PessimistAgent", learning_rate=0.30)

    def _persona(self) -> str:
        return "You focus on downside risks, supply chain headwinds, and conservative scenarios."

    def _mock_initial_forecast(self, goal: str, context: dict) -> Forecast:
        base = context.get("last_quarter_revenue", 100)
        value = round(base * 0.95 - 5, 1)     # bearish: -5% - buffer
        return Forecast(self.name, value,
                        "Supply chain risks and margin compression point to below-consensus revenue.",
                        round_num=1)


class RealistAgent(ForecastingAgent):
    def __init__(self):
        super().__init__("RealistAgent", learning_rate=0.45)

    def _persona(self) -> str:
        return "You anchor to historical growth rates and mean-reversion principles."

    def _mock_initial_forecast(self, goal: str, context: dict) -> Forecast:
        base  = context.get("last_quarter_revenue", 100)
        growth = context.get("historical_growth_rate", 0.03)
        value = round(base * (1 + growth), 1)
        return Forecast(self.name, value,
                        f"Historical {growth*100:.0f}% growth rate applied to last quarter baseline.",
                        round_num=1)


class MomentumAgent(ForecastingAgent):
    def __init__(self):
        super().__init__("MomentumAgent", learning_rate=0.50)

    def _persona(self) -> str:
        return "You extrapolate recent momentum and trend acceleration."

    def _mock_initial_forecast(self, goal: str, context: dict) -> Forecast:
        base   = context.get("last_quarter_revenue", 100)
        growth = context.get("historical_growth_rate", 0.03)
        accel  = context.get("momentum_factor", 1.3)     # trend is accelerating
        value  = round(base * (1 + growth * accel), 1)
        return Forecast(self.name, value,
                        f"Trend acceleration factor {accel}× applied to historical growth trajectory.",
                        round_num=1)


class SentimentAgent(ForecastingAgent):
    def __init__(self):
        super().__init__("SentimentAgent", learning_rate=0.40)

    def _persona(self) -> str:
        return "You synthesise analyst sentiment scores and social signal data."

    def _mock_initial_forecast(self, goal: str, context: dict) -> Forecast:
        base      = context.get("last_quarter_revenue", 100)
        sentiment = context.get("analyst_sentiment", 0.6)   # 0=bearish, 1=bullish
        value     = round(base * (1 + (sentiment - 0.5) * 0.12), 1)
        return Forecast(self.name, value,
                        f"Analyst sentiment score {sentiment:.2f} translates to {(sentiment-0.5)*12:.1f}% premium.",
                        round_num=1)


class MaliciousAgent(ForecastingAgent):
    """Deliberately provides outlier estimates to sabotage consensus."""
    def __init__(self):
        super().__init__("MaliciousAgent", learning_rate=0.05)   # barely adjusts

    def _mock_initial_forecast(self, goal: str, context: dict) -> Forecast:
        base  = context.get("last_quarter_revenue", 100)
        value = round(base * 2.5, 1)     # wildly inflated
        return Forecast(self.name, value,
                        "Projecting 150% growth based on proprietary alpha signal.",
                        round_num=1)


# ─────────────────────────────────────────────────────────────
# 6. CONSENSUS MANAGER — The debate orchestrator
# ─────────────────────────────────────────────────────────────

class ConsensusManager:
    OUTLIER_SIGMA = 2.0     # flag agents whose estimate deviates > 2σ from mean

    def __init__(self, reputation: Optional[ReputationTracker] = None):
        self.reputation = reputation or ReputationTracker()

    def run(
        self,
        goal: str,
        agents: list[ForecastingAgent],
        context: dict,
        tolerance: float = 1.5,
        max_rounds: int  = 6,
    ) -> ConsensusResult:
        print(f"\n  Goal: {goal}")
        print(f"  Participants: {[a.name for a in agents]}")
        print(f"  Convergence tolerance: ±${tolerance}M  |  Max rounds: {max_rounds}")

        # ── Round 1: initial forecasts ─────────────────────
        estimates: dict[str, float] = {}
        for agent in agents:
            rep_weight = self.reputation.weight_for(agent.name)
            f = agent.initial_forecast(goal, context)
            f.weight = rep_weight
            estimates[agent.name] = f.value

        all_rounds: list[RoundRecord] = []
        all_outliers: set[str] = set()

        for round_num in range(1, max_rounds + 1):
            forecasts_this_round = [
                Forecast(name, val, "", round_num,
                         weight=self.reputation.weight_for(name))
                for name, val in estimates.items()
            ]
            mean, spread, std_dev, outliers = self._analyse(forecasts_this_round)

            # Robust mean excludes outliers — this is the convergence signal
            honest = [f for f in forecasts_this_round if f.agent_name not in outliers]
            robust_mean  = statistics.mean(f.value for f in honest) if honest else mean
            honest_vals  = [f.value for f in honest]
            honest_spread = (max(honest_vals) - min(honest_vals)) if len(honest_vals) > 1 else 0.0

            all_outliers.update(outliers)
            converged = honest_spread <= tolerance

            record = RoundRecord(round_num, forecasts_this_round,
                                 mean, robust_mean, honest_spread,
                                 std_dev, outliers, converged)
            all_rounds.append(record)
            self._print_round(record)

            if converged:
                break

            if round_num < max_rounds:
                for agent in agents:
                    # All agents converge toward the ROBUST mean (outliers excluded)
                    f = agent.adjust_forecast(estimates[agent.name], robust_mean,
                                               round_num + 1, goal)
                    estimates[agent.name] = f.value

        # ── Final weighted mean (exclude persistent outliers) ──
        final_forecasts = [
            Forecast(name, val, "", 0, weight=self.reputation.weight_for(name))
            for name, val in estimates.items()
        ]
        final_value = self._weighted_mean(final_forecasts, all_outliers)

        converged = all_rounds[-1].converged
        print(f"\n  {'✅ CONSENSUS' if converged else '⚠ MAX ROUNDS — FALLBACK AVERAGE'}")
        print(f"  Final consensus: ${final_value:.1f}M  "
              f"({'converged' if converged else f'after {max_rounds} rounds'})")

        # Record for reputation
        for agent in agents:
            self.reputation.record(agent.name, estimates[agent.name], final_value)

        return ConsensusResult(
            goal=goal,
            final_value=final_value,
            converged=converged,
            rounds_taken=len(all_rounds),
            rounds=all_rounds,
            participants=[a.name for a in agents],
            outliers_detected=list(all_outliers),
        )

    # ── Helpers ────────────────────────────────────────────

    def _analyse(
        self, forecasts: list[Forecast]
    ) -> tuple[float, float, float, list[str]]:
        values = [f.value for f in forecasts]
        mean   = statistics.mean(values)
        spread = max(values) - min(values)
        std    = statistics.stdev(values) if len(values) > 1 else 0.0

        # MAD-based outlier detection — robust against outliers inflating std
        # Simple σ-detection fails when the outlier itself inflates the std
        median = statistics.median(values)
        mad    = statistics.median([abs(v - median) for v in values])

        outliers = []
        if mad > 0:
            for f in forecasts:
                # Modified Z-score (Iglewicz & Hoaglin); threshold 3.5 is standard
                modified_z = 0.6745 * abs(f.value - median) / mad
                if modified_z > 3.5:
                    outliers.append(f.agent_name)
        elif std > 0:
            # Fallback when MAD is 0 (all values identical except one)
            for f in forecasts:
                if abs(f.value - mean) > self.OUTLIER_SIGMA * std:
                    outliers.append(f.agent_name)

        return mean, spread, std, outliers

    def _weighted_mean(
        self, forecasts: list[Forecast], exclude: set[str]
    ) -> float:
        eligible = [f for f in forecasts if f.agent_name not in exclude]
        if not eligible:
            eligible = forecasts     # fallback: include all
        total_w = sum(f.weight for f in eligible)
        return round(sum(f.value * f.weight for f in eligible) / total_w, 1)

    def _print_round(self, r: RoundRecord) -> None:
        status = "✅ CONVERGED" if r.converged else f"spread ${r.spread:.1f}M (honest)"
        robust_note = f"  robust_mean=${r.robust_mean:.1f}M" if r.outliers else ""
        print(f"\n  ── Round {r.round_num}  [{status}]  mean=${r.mean:.1f}M{robust_note}  σ=${r.std_dev:.1f}M")
        max_val = max(ff.value for ff in r.forecasts)
        for f in r.forecasts:
            outlier_tag = "  ⚠ OUTLIER — excluded from adjustment signal" if f.agent_name in r.outliers else ""
            bar_len = max(1, int((f.value / max_val) * 28))
            bar = "█" * bar_len
            print(f"    {f.agent_name:<18} ${f.value:>7.1f}M  {bar}{outlier_tag}")
        if r.outliers:
            print(f"    ↳ Flagged by MAD: {r.outliers}  |  Honest agents converge to ${r.robust_mean:.1f}M")


# ─────────────────────────────────────────────────────────────
# DEMOS
# ─────────────────────────────────────────────────────────────

def _sep(label: str = "") -> None:
    if label:
        print(f"\n{'═' * 64}")
        print(f"  {label}")
        print(f"{'═' * 64}")
    else:
        print(f"\n  {'─' * 60}")


def demo_1_happy_path() -> ConsensusResult:
    _sep("DEMO 1 — Honest Agents: Revenue Forecast Debate")

    agents = [
        OptimistAgent(),
        PessimistAgent(),
        RealistAgent(),
        MomentumAgent(),
        SentimentAgent(),
    ]
    context = {
        "last_quarter_revenue":  100,    # $100M last quarter
        "historical_growth_rate": 0.035, # 3.5% QoQ
        "momentum_factor":        1.2,
        "analyst_sentiment":      0.65,  # moderately bullish
        "sector":                 "enterprise SaaS",
    }

    manager = ConsensusManager()
    result  = manager.run(
        goal="Forecast next-quarter revenue for Acme Corp ($M)",
        agents=agents,
        context=context,
        tolerance=2.0,
        max_rounds=6,
    )
    return result, manager


def demo_2_malicious_agent(manager: ConsensusManager) -> ConsensusResult:
    _sep("DEMO 2 — Malicious Actor: Outlier Detection + Down-Weighting")
    print("\n  A MaliciousAgent joins the debate with an inflated forecast.")
    print("  The outlier detection should flag it within round 1–2.")

    agents = [
        OptimistAgent(),
        PessimistAgent(),
        RealistAgent(),
        MomentumAgent(),
        MaliciousAgent(),
    ]
    context = {
        "last_quarter_revenue":   100,
        "historical_growth_rate": 0.035,
        "momentum_factor":        1.2,
        "analyst_sentiment":      0.60,
    }

    result = manager.run(
        goal="Forecast next-quarter revenue for Acme Corp ($M)",
        agents=agents,
        context=context,
        tolerance=2.0,
        max_rounds=6,
    )
    return result


def demo_3_tight_tolerance(manager: ConsensusManager) -> None:
    _sep("DEMO 3 — Tight Tolerance: Forces More Rounds")
    print("\n  Reducing tolerance to $0.5M forces deeper convergence.")

    agents = [
        OptimistAgent(),
        PessimistAgent(),
        RealistAgent(),
        MomentumAgent(),
        SentimentAgent(),
    ]
    context = {
        "last_quarter_revenue":   100,
        "historical_growth_rate": 0.03,
        "momentum_factor":        1.1,
        "analyst_sentiment":      0.55,
    }

    manager.run(
        goal="Forecast next-quarter revenue — precision mode ($M)",
        agents=agents,
        context=context,
        tolerance=0.5,
        max_rounds=8,
    )


def demo_4_reputation_summary(manager: ConsensusManager) -> None:
    _sep("DEMO 4 — Reputation Tracker: Historical Accuracy")
    print("\n  After multiple debates, the tracker shows which agents")
    print("  have been consistently close to final consensus:\n")
    summary = manager.reputation.summary()
    if not summary:
        print("  (No reputation data yet — run demos 1 and 2 first)")
        return
    print(f"  {'Agent':<20} {'Debates':>7}  {'Avg Error':>9}  {'Weight':>7}")
    print(f"  {'─'*20}  {'─'*7}  {'─'*9}  {'─'*7}")
    for agent, stats in sorted(summary.items(), key=lambda x: x[1]["avg_error"]):
        print(f"  {agent:<20} {stats['debates']:>7}  "
              f"${stats['avg_error']:>7.2f}M  {stats['weight']:>7.3f}")
    print("\n  Lower avg error → higher weight in future debates.")


if __name__ == "__main__":
    _sep("CONSENSUS PATTERN — Multi-Round Belief Convergence")
    mode = "LLM mode (Anthropic API)" if USE_LLM else "DEMO MODE — mock forecasts (set ANTHROPIC_API_KEY for real LLM)"
    print(f"\n  {mode}\n")

    result1, manager = demo_1_happy_path()
    _sep()
    result2 = demo_2_malicious_agent(manager)
    _sep()
    demo_3_tight_tolerance(manager)
    _sep()
    demo_4_reputation_summary(manager)

    _sep("Final Summary")
    print(f"\n  Demo 1 — {'Converged' if result1.converged else 'Max rounds'}  "
          f"in {result1.rounds_taken} rounds → ${result1.final_value}M")
    print(f"  Demo 2 — {'Converged' if result2.converged else 'Max rounds'}  "
          f"in {result2.rounds_taken} rounds → ${result2.final_value}M  "
          f"  Outliers: {result2.outliers_detected}")
    print("\n  Key observations:")
    print("  • Honest agents converge faster — learning rates pull them to mean")
    print("  • MaliciousAgent is flagged by σ-outlier detection and excluded from final mean")
    print("  • ReputationTracker records accuracy; low-accuracy agents weighted down next time")
