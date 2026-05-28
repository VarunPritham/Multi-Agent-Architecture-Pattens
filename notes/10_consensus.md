# Consensus
## Multi-Round Belief Convergence + Outlier Detection

---

## What Problem Does This Solve?

In a distributed multi-agent system, different agents perceive the world differently. An OptimistAgent reads bullish signals; a PessimistAgent reads bearish ones. Both are rational given their data. But the system cannot act on two contradictory numbers — it needs one agreed-upon value.

The Consensus pattern solves this through a structured debate: agents broadcast their current belief, observe the collective mean, and iteratively adjust toward it. The process terminates when all estimates fall within a tolerance band — a "close enough" agreement that allows coordinated action.

The deeper challenge is robustness: what if one agent is wrong, biased, or malicious? A naive average gets poisoned. The Consensus pattern addresses this with outlier detection and robust statistics, ensuring that a single bad actor cannot derail the group.

---

## The Protocol — Three Phases

### Phase 1: Initial Forecasts (Round 1)

Each agent generates its best estimate independently, without seeing the others:

```
OptimistAgent:    $115M  ("strong demand signals and positive macro tailwinds")
PessimistAgent:   $90M   ("supply chain risks and margin compression")
RealistAgent:     $103.5M ("3.5% QoQ growth applied to last quarter baseline")
MomentumAgent:    $104.2M ("trend acceleration factor applied to trajectory")
SentimentAgent:   $101.8M ("analyst sentiment score 0.65 translates to 3% premium")
```

### Phase 2: Iterative Adjustment

After each round, agents observe the **robust mean** (the group mean excluding flagged outliers) and pull their estimate toward it by a `learning_rate`:

```python
adjusted = current + learning_rate * (robust_mean - current)
```

The learning_rate is agent-specific:
- Conservative agents (PessimistAgent, lr=0.30) adjust slowly — they believe their data is reliable
- Moderate agents (OptimistAgent, lr=0.35) adjust at a medium rate
- Open agents (RealistAgent, lr=0.45) adjust more readily toward consensus

### Phase 3: Convergence Check

The protocol terminates when:
- `max(honest) - min(honest) <= tolerance` — consensus reached ✅
- OR `round_num == max_rounds` — fallback to weighted mean ⚠

---

## Why Simple σ-Based Outlier Detection Fails

The naive approach: flag any agent whose estimate deviates more than 2σ from the mean.

**The problem**: when a MaliciousAgent reports $250M among honest estimates of $90–115M:

```
Values: [115, 90, 103.5, 104.2, 250]
Mean:   $132.5M
Std:    $66.3M
2σ threshold: $132.6M

MaliciousAgent deviation: |$250 - $132.5| = $117.5M < $132.6M → NOT FLAGGED
```

The outlier inflates both the mean and the std, making its own detection threshold too high to cross. This is a fundamental flaw in σ-based detection on small samples.

---

## MAD-Based Outlier Detection — The Fix

Median Absolute Deviation (MAD) uses the median, which is immune to extreme outliers:

```python
median = statistics.median(values)                         # 103.5 — unaffected by 250
mad    = statistics.median([abs(v - median) for v in values])   # = 11.5

# Modified Z-score (Iglewicz & Hoaglin 1993):
modified_z = 0.6745 * abs(f.value - median) / mad

# For MaliciousAgent: 0.6745 * |250 - 103.5| / 11.5 = 8.59 > 3.5 → FLAGGED ✅
# For OptimistAgent:  0.6745 * |115 - 103.5| / 11.5 = 0.67 < 3.5 → not flagged ✅
```

**Why this works**: the median of `[90, 103.5, 104.2, 115, 250]` is 103.5 — the outlier doesn't move it. The MAD is 11.5 — the outlier doesn't inflate it. The threshold for detection is stable regardless of how extreme the outlier is.

---

## The Robust Mean — Protecting the Convergence Signal

Even after an outlier is detected, the raw group mean is still poisoned. If honest agents adjust toward `$132.5M` instead of `$103.2M`, they drift away from the truth.

The fix: always compute a **robust mean** from non-outlier agents, and use it as the adjustment signal:

```python
honest = [f for f in forecasts if f.agent_name not in outliers]
robust_mean = statistics.mean(f.value for f in honest)
# For demo: [115, 90, 103.5, 104.2] → $103.2M ← honest agents converge to this
```

Agents adjust toward `robust_mean`, not `mean`. The malicious agent is structurally isolated — it still participates (so it can be monitored), but its value does not influence where honest agents move.

---

## Convergence Condition — Honest Spread Only

The tolerance check also uses honest agents only:

```python
honest_vals   = [f.value for f in forecasts if f.agent_name not in outliers]
honest_spread = max(honest_vals) - min(honest_vals)
converged     = honest_spread <= tolerance
```

In Demo 2, by round 6 the honest agents have a spread of `$3.6M`. The MaliciousAgent is still at `$216.7M`, but the consensus system correctly declares convergence among honest agents and excludes the outlier from the final value.

---

## ReputationTracker — Long-Term Accountability

The ConsensusManager records each agent's accuracy after every debate:

```python
class ReputationTracker:
    def record(self, agent_name, estimate, final_consensus):
        err = abs(estimate - final_consensus)
        self._history.setdefault(agent_name, []).append(err)

    def weight_for(self, agent_name) -> float:
        avg_error = statistics.mean(self._history[agent_name])
        return max(0.3, 1.0 - avg_error / 50.0)
```

After multiple debates:
- RealistAgent: avg_error $0.17M → weight 0.997 (nearly full weight)
- OptimistAgent: avg_error $3.23M → weight 0.935 (slight discount)
- MaliciousAgent: avg_error $114M → weight 1.0 (only one debate so far, then plummets)

In the next debate, the weighted mean downweights agents with poor track records. After three debates, MaliciousAgent's weight would drop to ~0.30 (the floor) — its contributions are nearly ignored even if it evades outlier detection.

---

## Audit Trail — Explaining the Decision

Every round produces a `RoundRecord` with full provenance:

```
Round 2  [✅ CONVERGED]  mean=$102.8M  robust_mean=$103.1M  σ=$6.0M
  OptimistAgent      $110.9M  ████████  ⚠ OUTLIER — excluded from adjustment signal
  PessimistAgent     $94.0M   ██████    ⚠ OUTLIER — excluded from adjustment signal
  RealistAgent       $103.3M  ████████
  MomentumAgent      $103.7M  ████████
  SentimentAgent     $102.3M  ████████
  ↳ Flagged by MAD: [OptimistAgent, PessimistAgent]  |  Honest agents converge to $103.1M
```

This record answers: "Why $103.1M?" You can trace every adjustment, every outlier flag, and every learning rate applied. For regulated industries (financial services, healthcare) this audit trail is a compliance requirement.

---

## Comparison: Consensus vs Other Patterns

| Pattern | Handles conflict? | Handles bad actors? | Adapts over time? |
|---|---|---|---|
| Supervisor | No — orchestrator decides | No | No |
| Blackboard | Yes — facts compete by confidence | Partially (low confidence) | Within session |
| Contract-Net | No — single winner | No (reputation helps) | Via reputation |
| **Consensus** | **Yes — structured convergence** | **Yes — MAD outlier detection** | **Yes — reputation weighting** |

---

## Pros and Cons

### Pros
- **Reliability**: multiple agents validate a value before action — reduces single-agent error
- **Fault tolerance**: one agent failing or abstaining doesn't halt the process
- **Robustness**: MAD detection isolates bad actors structurally, not just via trust scores
- **Explainability**: full round-by-round audit trail — every adjustment is logged
- **Improves over time**: reputation tracker down-weights consistently wrong agents

### Cons
- **Latency**: multiple rounds of communication before any action is taken
- **Agreement ≠ accuracy**: agents can converge on a wrong value if most have the same bias
- **Parameter sensitivity**: tolerance, max_rounds, and learning_rate all require careful tuning
- **Honest majority assumption**: outlier detection works when dishonest agents are a minority — if most agents are malicious, the "robust mean" is wrong

---

## When to Use

✅ Use when:
- Multiple agents have different (but valid) perspectives on the same quantity
- The cost of acting on wrong information is high (financial, medical, infrastructure)
- You need a documented audit trail of how a decision was reached
- The environment contains potential bad actors or noisy data sources

❌ Avoid when:
- Real-time decisions are required — multiple rounds add latency
- There is a clear "ground truth" accessible to a single agent — no need for debate
- All agents have identical data sources — they'll agree in round 1 regardless

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `consensus.py` | Full financial forecasting debate — 5 specialist agents, MAD outlier detection, robust mean adjustment, reputation tracking, 4-demo walkthrough |

---

## Real-World Equivalents

- **Jury deliberation**: jurors (agents) hold initial verdicts, hear each other's reasoning, and adjust. The jury must reach unanimous (or supermajority) agreement before a verdict is issued.
- **Central bank interest rate decisions**: committee members submit individual rate recommendations, discuss, and converge on a single policy rate over multiple rounds.
- **Clinical diagnosis panel**: specialists from different disciplines each give a diagnosis; a consensus is reached when enough agree, with outlier diagnoses noted but not ignored.
- **Distributed sensor fusion**: sensors report conflicting temperature readings; a fusion algorithm detects faulty sensors (MAD) and computes a robust mean for the control system.
- **IETF / standards bodies**: multiple companies propose competing protocol specifications; iterative balloting and comment rounds converge on a single standard.
