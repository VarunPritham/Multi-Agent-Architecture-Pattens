Create a new Blackboard Knowledge Hub implementation for the following domain: $ARGUMENTS

Follow the Blackboard pattern exactly:

**Step 1 — Define FactType enum and Fact model**
- `FactType` enum appropriate to domain:
  - Always include: OBSERVATION (raw input), HYPOTHESIS, TEST_REQUEST, DATA_RESULT, ASSESSMENT, CONCLUSION
  - Add domain-specific types if needed
- `Fact` dataclass: fact_id, agent_id, fact_type, content, confidence (0.0–1.0), timestamp, metadata dict
- Facts are immutable once posted — never edit, only append

**Step 2 — Build the Blackboard**
- `threading.Lock()` for all writes
- `post(agent_id, fact_type, content, confidence, metadata) → Fact`
- `get_facts(fact_type=None, min_confidence=0.0) → list[Fact]`
- `contains_keyword(keyword, fact_types, min_confidence) → bool`
- `has_fact_type(fact_type) → bool`
- `check_convergence() → bool` — configure threshold (e.g., ≥1 CONCLUSION at ≥0.75 conf with ≥3 supporting facts)

**Step 3 — Build BaseKnowledgeSource**
- `__init__(agent_id, board)` + `self._done = False`
- Abstract `is_eligible() → bool` — reads board, never posts
- Abstract `contribute()` — reads board, posts facts, sets `self._done = True`
- Helper `_post_contributions(list[tuple])` — loops over (content, confidence, fact_type) tuples

**Step 4 — Build 4–5 specialist agents**
Design a cascade where each agent's output enables the next:
- Agent 1: triggers on OBSERVATION → posts initial HYPOTHESIS
- Agent 2: triggers on keyword in HYPOTHESIS (e.g., "fraud", "infection") → posts ASSESSMENT
- Agent 3: triggers on ASSESSMENT → posts TEST_REQUEST for more data
- Agent 4: triggers on TEST_REQUEST → posts DATA_RESULT (lab/API results)
- Agent 5: triggers when DATA_RESULT + high-confidence HYPOTHESIS both exist → posts CONCLUSION

Each eligibility check must include:
1. `not self._done`
2. A specific fact type or keyword condition
3. Optional: minimum confidence gate on triggering facts

**Step 5 — Build the BlackboardController**
- Seeds board with raw problem as an OBSERVATION fact (confidence 1.0)
- Loop up to `MAX_CYCLES = 8`:
  - `eligible = [ks for ks in sources if ks.is_eligible()]`
  - If empty → break (no progress possible)
  - Run each eligible agent
  - Check convergence → break if reached
- Return highest-confidence CONCLUSION fact

**Step 6 — Demo + Audit trail**
- Run 1 complete problem-solving session
- Print full audit trail: every fact in order with ID, type, agent, confidence, content
- Mark the conclusion fact with ★
- Print the final answer separately with confidence and posting agent

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/blackboard_<domain>.py
