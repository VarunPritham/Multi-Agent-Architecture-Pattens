Create a new Consensus implementation for the following domain: $ARGUMENTS

Follow the Consensus pattern exactly:

**Step 1 — Define Forecast, RoundRecord, and ConsensusResult dataclasses**
- `Forecast`: agent_name, value (float), reasoning, round_num (int), weight (float=1.0), is_outlier (bool=False)
- `RoundRecord`: round_num, forecasts (list[Forecast]), mean, robust_mean, spread (honest only), std_dev, outliers (list[str]), converged (bool)
- `ConsensusResult`: goal, final_value, converged, rounds_taken, rounds (list[RoundRecord]), participants (list[str]), outliers_detected (list[str])

**Step 2 — Build ReputationTracker**
- `record(agent_name, estimate, final_consensus)` — append `abs(estimate - final_consensus)` to agent's history
- `weight_for(agent_name) → float` — `max(0.3, 1.0 - avg_error / scale)` for agents with ≥2 debates; return 1.0 for new agents
- `summary() → dict` — agent → {debates, avg_error, weight}, sorted by avg_error

**Step 3 — Build ForecastingAgent base + minimum 4 domain specialists + MaliciousAgent**
- `ForecastingAgent.__init__(name, learning_rate)` — learning_rate ∈ [0,1]
- `initial_forecast(goal, context) → Forecast` — LLM or mock
- `adjust_forecast(current, group_mean, round_num, goal) → Forecast`
  - Formula: `adjusted = current + learning_rate * (group_mean - current)`
- `_llm_forecast()`: `submit_forecast` tool_use returning `{value, reasoning}`
- `_mock_initial_forecast()`: subclass override — compute from context dict values
- Each specialist: different bias (optimist/pessimist/realist/etc.), different learning_rate
- `MaliciousAgent`: `learning_rate=0.05`, reports wildly inflated/deflated value

**Step 4 — Build ConsensusManager**
- `run(goal, agents, context, tolerance, max_rounds) → ConsensusResult`:
  1. Round 1: call `agent.initial_forecast(goal, context)` for all agents
  2. For round_num in 1..max_rounds:
     a. `mean, spread, std_dev, outliers = _analyse(forecasts_this_round)`
     b. Compute `robust_mean` = mean of non-outlier forecasts
     c. `honest_spread` = max - min among non-outlier values
     d. `converged = honest_spread <= tolerance`
     e. Create RoundRecord, append to all_rounds, call `_print_round(record)`
     f. If converged: break
     g. All agents adjust toward `robust_mean` (not raw mean)
  3. Final value = `_weighted_mean(final_forecasts, all_outliers)`
  4. Record reputation for all agents
- `_analyse(forecasts)`: **MUST use MAD-based detection** (see below)
- `_weighted_mean(forecasts, exclude) → float`: weight by reputation, exclude persistent outliers
- `_print_round(record)`: bar chart (proportional █ fill), outlier tags, round summary line

**MAD-based outlier detection (mandatory):**
```python
median = statistics.median(values)
mad    = statistics.median([abs(v - median) for v in values])
if mad > 0:
    for f in forecasts:
        modified_z = 0.6745 * abs(f.value - median) / mad
        if modified_z > 3.5:
            outliers.append(f.agent_name)
elif std > 0:  # fallback
    for f in forecasts:
        if abs(f.value - mean) > 2.5 * std:
            outliers.append(f.agent_name)
```
**Never use simple σ-based detection — the outlier inflates its own threshold.**

**Step 5 — Four demos**
- Demo 1: Honest agents, moderate tolerance → converges in 2–4 rounds; show round-by-round bar charts
- Demo 2: Include MaliciousAgent → flagged in round 1, honest agents unaffected, final value correct
- Demo 3: Tight tolerance → forces more rounds, max_rounds reached, fallback to weighted average
- Demo 4: ReputationTracker summary → show MaliciousAgent with large avg_error

**Round print format:**
```
── Round N  [✅ CONVERGED | spread $X.XM (honest)]  mean=$X.XM  [robust_mean=$X.XM]  σ=$X.XM
  AgentName          $ XXX.XM  ████████████  ⚠ OUTLIER — excluded from adjustment signal
  AgentName          $ XXX.XM  ████████████
  ↳ Flagged by MAD: [AgentName]  |  Honest agents converge to $X.XM
```

**Reputation table format (Demo 4):**
```
  Agent                Debates  Avg Error   Weight
  ────────────────────  ───────  ─────────  ───────
  RealistAgent               3  $   0.17M    0.997
  MaliciousAgent             1  $ 114.12M    1.000
```

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/consensus_<domain>.py
