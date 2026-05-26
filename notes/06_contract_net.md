# Contract-Net Marketplace
## Market-Based Dynamic Task Allocation

---

## What Problem Does This Solve?

In a system with multiple agents that can handle the same class of task, who should get the job? The answer depends on factors that are only known at runtime:
- Which agents are online right now?
- What is each agent's current cost and expected turnaround?
- Does this specific task favour speed over cost, or quality over both?

Static routing (capability graphs, pre-assigned workers) can't account for these dynamic factors. The Contract-Net Protocol solves this by running a **miniature market** for every task — the most suitable agent wins the contract, where "most suitable" is defined by the task's own utility weights.

---

## The Three Roles

```
Solicitor                    Bidder Agents
─────────                    ─────────────
1. Announce task      →      Evaluate capability
                      ←      Submit bid (cost, ETA, confidence)
2. Score all bids            [or refuse if constraints violated]
3. Award contract     →      Execute task
4. Record outcome            Report actual quality
```

The **solicitor** never executes work — it runs the auction and delegates. The **bidder agents** know their own capabilities and costs. The **utility function** is the decision rule that converts competing bids into a single winner.

---

## The Task Announcement

Every announcement carries two kinds of information:

**Constraints** — hard limits. A bid that violates any constraint is refused before scoring:
```python
max_cost:       100.0    # USD ceiling
max_eta_hours:  3.0      # time ceiling
min_confidence: 0.85     # quality floor
```

**Utility weights** — the solicitor's priorities for this specific task:
```python
weight_cost:        0.6   # budget job — cost matters most
weight_eta:         0.2
weight_confidence:  0.2
```

The same pool of agents produces different winners for different weight profiles. An OnPrem agent that wins a budget job loses the same task when the weights shift to speed.

---

## The Utility Function — The Core Design Decision

```
utility = (conf_score × w_conf) + ((1 - cost_score) × w_cost) + ((1 - eta_score) × w_eta)
        × reputation_multiplier
```

**Normalisation**: scores are computed relative to the bid set, not globally. The cheapest bid gets `cost_score = 0` (best), the most expensive gets `cost_score = 1` (worst). This means the utility score is always between 0 and 1 regardless of the absolute values.

**Why this matters**: without normalisation, a $10 difference between bids and a 0.01 confidence difference would have wildly disproportionate effects depending on scale.

**Per-task weights**: the weights are set on the `TaskAnnouncement`, not globally. Every task can declare its own priority:

| Scenario | weight_cost | weight_eta | weight_confidence |
|---|---|---|---|
| Budget-constrained | 0.6 | 0.2 | 0.2 |
| Speed-critical | 0.2 | 0.6 | 0.2 |
| Quality-critical | 0.2 | 0.2 | 0.6 |
| Balanced | 0.33 | 0.33 | 0.33 |

---

## Hard Refusal vs Soft Competition

These are different mechanisms and must not be confused:

**Hard refusal** (constraint violation) — agent declines before bidding:
```python
if task.max_cost and estimated_cost > task.max_cost:
    print(f"[{self.agent_id}] Refusing — ${cost} exceeds max ${task.max_cost}")
    return None
```
The agent is removed from the auction entirely. It doesn't appear in the scoring.

**Soft competition** (utility scoring) — agent bids but may score poorly:
An agent with high cost but excellent confidence will still appear in the scored leaderboard. The utility function may still prefer it if `weight_confidence` is high enough.

---

## Reputation System — Penalising Overpromisers

Agents that consistently bid 90% confidence but deliver 75% should lose future contracts to honest bidders. The reputation multiplier captures this:

```
delta = actual_quality - promised_confidence

Average delta over history:
  +0.05 → reputation = 1.05x  (consistently underestimates, delivers more)
  -0.15 → reputation = 0.85x  (consistently overpromises)
   0.00 → reputation = 1.00x  (neutral)
```

Range: clamped to [0.5, 1.2]. An agent with a 0.85x reputation needs to be substantially better on raw utility to overcome the penalty.

**Why this matters in production**: without reputation, every agent is incentivised to claim maximum confidence to win every bid. Reputation makes honest self-assessment the dominant strategy.

---

## Bid Timeout — Preventing Infinite Waiting

The solicitor must enforce a deadline for receiving bids:

```python
BID_TIMEOUT_SECONDS = 2.0   # demo; production: 30–60s

threads = [Thread(target=collect_bid, args=(a,)) for a in agents]
for t in threads: t.start()
for t in threads: t.join(timeout=BID_TIMEOUT_SECONDS)
# Collect whatever arrived — don't wait for stragglers
```

Without a timeout, a single slow or offline agent blocks the entire auction. Agents that don't respond within the deadline are simply excluded from scoring.

---

## NoBidsException — Graceful Handling

When zero bids are received (all agents offline, or constraints too tight):

```python
if not bids:
    raise NoBidsException(
        f"No agent could fulfill task '{task.task_id}'. "
        f"Consider relaxing constraints."
    )
```

The caller handles this — either by relaxing constraints and re-announcing, falling back to a default agent, or escalating to a human. It must never crash silently.

---

## Pros and Cons

### Pros
- **Dynamic selection**: the right agent is chosen at runtime based on actual availability and cost
- **Self-describing agents**: each agent knows its own capabilities and refuses tasks it can't handle
- **Incentive-aligned**: reputation system rewards honest bidding over time
- **No code changes to add agents**: new bidder registers itself; solicitor discovers it automatically

### Cons
- **Auction latency**: the broadcast-collect-score cycle adds overhead before work begins
- **Gaming risk**: without reputation, agents may inflate confidence to win bids
- **Coordination cost**: every task requires a full auction, even if one agent is clearly the best fit
- **SLA tension**: waiting for bids conflicts with tight execution deadlines

---

## When to Use

✅ Use when:
- Multiple agents can handle the same task type but differ in cost, speed, or quality
- Agent availability and load fluctuate at runtime
- You want to optimise for different priorities on a per-task basis (cost vs speed vs quality)
- You're operating in a multi-cloud or multi-vendor environment

❌ Avoid when:
- One agent is always the clear best fit (use Agent Router — simpler, lower latency)
- The workflow is strictly sequential with pre-known agents (use Supervisor)
- Task volume is very high and auction latency is unacceptable (consider caching or pre-selection)

---

## Comparison: Agent Router vs Contract-Net

Both route tasks to agents, but they solve different problems:

| | Agent Router | Contract-Net |
|---|---|---|
| Selection mechanism | Capability graph (static) | Competitive bidding (dynamic) |
| Adapts to load/cost? | No | Yes |
| Latency | One LLM call + dict lookup | Broadcast + collect + score |
| Best for | Stable, known agent capabilities | Dynamic pools with variable cost/availability |

Use Agent Router when you know which agent handles which task. Use Contract-Net when multiple agents can do the job and you want the best one right now.

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `contract_net_marketplace.py` | Full cloud ML training marketplace — 5 providers, 5 scenarios (budget/speed/quality/reputation/no-bids), utility scoring, reputation tracking |

---

## Real-World Equivalents

- **Freelance job boards** (Upwork, Fiverr): client posts requirements, freelancers bid, client picks best value
- **Cloud spot markets**: AWS/GCP sell unused capacity via real-time auctions
- **Ride-sharing dispatch**: driver bids implicitly via proximity/rating; platform picks the optimal match
- **Ad auction (RTB)**: publisher broadcasts impression, DSPs bid in milliseconds, highest utility wins
