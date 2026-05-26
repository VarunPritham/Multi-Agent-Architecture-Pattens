Create a new Contract-Net Marketplace implementation for the following domain: $ARGUMENTS

Follow the Contract-Net pattern exactly:

**Step 1 — Define TaskAnnouncement**
- Fields: task_id, task_type (Literal), description
- Constraint fields: max_cost, max_eta_hours, min_confidence (all Optional)
- Payload fields: domain-specific parameters that affect how hard the task is
- Utility weight fields: weight_cost, weight_eta, weight_confidence (floats, ~sum to 1.0)

**Step 2 — Define Bid and NoBidsException**
- Bid fields: agent_id, task_id, cost (float), eta_hours (float), confidence (0.0–1.0), resource_description (str), notes (str)
- NoBidsException: raised by solicitor when zero bids received

**Step 3 — Build BidderAgent base class**
- `receive_announcement(task) → Optional[Bid]`:
  1. Return None if agent is offline
  2. Estimate cost, ETA, confidence using domain-specific logic
  3. Hard refusal with print message if any constraint is violated
  4. Return a Bid if all constraints are met
- `execute_contract(task, bid) → dict`: simulate execution with ±5% variance on cost/time, ±3% on quality
- `_estimate_cost`, `_estimate_eta`, `_assess_confidence`: override in subclasses

**Step 4 — Build 4–5 specialised bidder agents**
Design agents with meaningfully different profiles so different scenarios pick different winners:
- Agent A: fast and expensive, high confidence (wins speed-critical tasks)
- Agent B: medium speed, medium cost, solid confidence (balanced option)
- Agent C: slow and cheap, lower confidence (wins budget-constrained tasks)
- Agent D: domain specialist — high confidence on specific task types, mid cost
- Agent E: spot/preemptible — very cheap but unreliable confidence (loses quality-critical tasks)

Each agent should override at least one of the estimation methods with domain-specific logic.

**Step 5 — Build ReputationTracker**
- `record_outcome(agent_id, promised_confidence, actual_quality)`: append delta to agent's history
- `get_reputation(agent_id) → float`: average delta clamped to [0.5, 1.2], default 1.0 for new agents
- `summary() → dict`: return {agent_id: "X.XXx"} for all tracked agents

**Step 6 — Build Solicitor**
- `BID_TIMEOUT_SECONDS = 2.0`
- `_broadcast_and_collect(task)`: launch one thread per agent, join with timeout, collect bids
- `_score_bids(bids, task)`:
  - Normalise cost, eta, confidence within the bid set to [0,1]
  - Compute: `utility = conf_score*w_conf + (1-cost_score)*w_cost + (1-eta_score)*w_eta`
  - Multiply by `reputation.get_reputation(bid.agent_id)`
  - Return sorted list of (Bid, utility_score) descending
- `request_task_fulfillment(task)`:
  1. Broadcast → collect bids
  2. Raise NoBidsException if empty
  3. Score bids (print full leaderboard)
  4. Award to highest utility (print winner)
  5. Execute contract via winning agent
  6. Record outcome in reputation tracker
  7. Return result dict

**Step 7 — Demo with 5 scenarios**
- Scenario 1: Budget-constrained (weight_cost=0.6) — cheap agent wins
- Scenario 2: Speed-critical (weight_eta=0.6, max_eta constraint) — fast agent wins; slow agents refuse
- Scenario 3: Quality-critical (min_confidence, weight_confidence=0.6) — low-conf agents self-refuse
- Scenario 4: Reputation effect — print reputation scores, rerun similar task, show shifted outcome
- Scenario 5: NoBidsException — all agents offline or constraints impossible to meet

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/contract_net_<domain>.py
