# Multi Agent Architectures

> Work in progress — learning and experimenting with agentic design patterns.

---

## What This Is

A hands-on study of multi-agent architecture patterns, built alongside reading a book on agentic systems. Each pattern is explained, implemented in Python, and documented with notes. Not production code — the goal is to understand the patterns deeply enough to apply them.

---

## What's Covered So Far

### 1. Agent Router
Intent-based routing — maps natural language to the right agent via LLM extraction + a capability graph whitelist. The "Hello World" of agentic coordination.
→ `router.py` · `notes/01_agent_router.md`

### 2. Supervisor Architecture
Centralized orchestration — one orchestrator coordinates specialized workers in a sequential workflow. Best for regulated, auditable processes.
→ `supervisor_architecture.py` · `notes/02_supervisor_architecture.md`

### 3. Swarm Architecture
Decentralized coordination — agents poll a shared task board and self-select work. No central controller. Workflow emerges from status transitions.
→ `swarm_architecture.py` · `notes/03_swarm_architecture.md`

### 4. Blackboard Knowledge Hub
Iterative convergence — specialists post typed, confidence-weighted facts to a shared board until enough evidence accumulates for a conclusion.
→ `blackboard_hub.py` · `notes/04_blackboard_hub.md`

### 5. Contract-Net Marketplace
Market-based task allocation — a solicitor broadcasts a task, bidder agents respond with cost/ETA/confidence bids, and a utility function picks the winner at runtime. Adapts to dynamic agent availability.
→ `contract_net_marketplace.py`

### 6. Supervision Tree with Guarded Capabilities
Fault isolation + least privilege — agents are organised into a hierarchy where supervisors manage child lifecycle (restart, backoff, escalate) and each agent is spawned with only the tools it needs.
→ `supervision_tree.py` · `notes/05_supervision_tree.md`

### 7. Multi-Agent Planning
Goal decomposition + dependency-aware execution — a planning agent breaks a high-level goal into a dependency graph of sub-tasks, runs independent tasks in parallel, gates dependent tasks, and replans dynamically on failure.
→ `multi_agent_planning.py` · `notes/07_multi_agent_planning.md`

### 8. Knowledge Sharing
Shared epistemic memory — agents write discoveries to a collective knowledge base and retrieve semantically similar entries via TF-IDF cosine similarity. Trust signals (peer ratings, use counts) surface the best knowledge; a governance agent deprecates low-quality entries. The system gets smarter with every query.
→ `knowledge_sharing.py` · `notes/08_knowledge_sharing.md`

### 9. Tool Routing
Scoped tool dispatch — a central router classifies intent via LLM tool_use and delegates to a specialist; each specialist is instantiated with only its own tools (no cross-contamination). A ToolRegistry is the single source of truth; adding a new agent requires only registry calls — the router adapts automatically.
→ `tool_routing.py` · `notes/09_tool_routing.md`

### 10. Consensus
Multi-round convergence — a group of agents broadcast their beliefs, observe the collective mean, and iteratively adjust toward agreement. An outlier-detection layer identifies and down-weights agents providing systematically bad data. The process terminates on convergence or max rounds, with a full audit trail of every round.
→ `consensus.py` · `notes/10_consensus.md`

### 11. Agent Negotiation
Structured offer/counter-offer protocol — a mediator detects scheduling conflicts, grants the highest-priority agent its slot, and asks lower-priority agents to propose alternatives within their flexibility constraints. RIGID agents that cannot move fall back to forced resolution. Full audit transcript + ASCII timeline.
→ `negotiation.py` · `notes/11_negotiation.md`

### 12. Resource Allocation
Priority-aware dispatch with anti-starvation, preemption, and auction bidding — a pool of shared resources is dispatched to competing agents using a tick-based simulation. Supports three strategies (PRIORITY_QUEUE, AUCTION, FAIR_SHARE), age-based priority boosting to prevent starvation, and CRITICAL preemption that can interrupt a running lower-priority task.
→ `resource_allocation.py` · `notes/12_resource_allocation.md`

### 13. Conflict Resolution
Structured detection and multi-strategy mediation — a SupervisorAgent intercepts competing plans before execution and resolves them using one of four strategies: policy-based rules (compliance overrides speed), hierarchical authority (priority wins), iterative negotiation (flexible agents propose alternatives), or game-theoretic Nash equilibrium (self-interest aligned with global optimum). Full audit trail on every decision.
→ `conflict_resolution.py` · `notes/13_conflict_resolution.md`

### 14. Formation Control
Decentralized swarm coordination via local neighbor rules — each agent maintains a fixed positional offset from one designated neighbor using a proportional controller. No central planner. Collective shape (line, V, grid) emerges from local sensing. Obstacle repulsion cascades through the neighbor chain and the formation self-repairs.
→ `formation_control.py` · `notes/14_formation_control.md`

---

## How to Follow

**Read the notes first** — each `notes/0X_*.md` file explains the concept, the mechanics, when to use it, and what tradeoffs to expect. Takes 5 minutes per pattern.

**Then read the code** — the Python files are structured to mirror the notes. Comments are minimal by design; the structure itself is the explanation.

**Run the demos** — every file has a `if __name__ == "__main__"` block with multiple test cases. All run in demo mode without an API key. Set `ANTHROPIC_API_KEY` to use real LLM calls.

```bash
python router.py
python supervisor_architecture.py
python swarm_architecture.py
python blackboard_hub.py
python contract_net_marketplace.py
python supervision_tree.py
python multi_agent_planning.py
python knowledge_sharing.py
python tool_routing.py
python consensus.py
python negotiation.py
python resource_allocation.py
python conflict_resolution.py
python formation_control.py
```

**Scaffold new patterns** — slash commands in `.claude/commands/` let you generate a new implementation for any domain:
```
/create-agent-router           <your domain>
/create-supervisor             <your domain>
/create-swarm                  <your domain>
/create-blackboard             <your domain>
/create-supervision-tree       <your domain>
/create-contract-net           <your domain>
/create-multi-agent-planning   <your domain>
/create-knowledge-sharing      <your domain>
/create-tool-routing           <your domain>
/create-consensus              <your domain>
/create-negotiation            <your domain>
/create-resource-allocation   <your domain>
/create-conflict-resolution   <your domain>
/create-formation-control     <your domain>
```

---

## Suggested Order

1. Agent Router — understand intent extraction and routing before anything else
2. Supervisor — learn centralized control, checkpointing, structured handoffs
3. Swarm — contrast with Supervisor; understand pull-based, emergent coordination
4. Blackboard — iterative knowledge convergence for ill-defined problems
5. Contract-Net — market-based dynamic agent selection at runtime
6. Supervision Tree — fault isolation and least-privilege capability guarding
7. Multi-Agent Planning — decompose goals into parallel dependency graphs
8. Knowledge Sharing — collective memory, semantic retrieval, trust-driven quality
9. Tool Routing — scoped tool dispatch, dynamic registry, two-level routing
10. Consensus — iterative belief convergence, outlier detection, audit trail
11. Agent Negotiation — offer/counter-offer protocol, flexibility constraints, forced resolution
12. Resource Allocation — priority dispatch, anti-starvation boosts, CRITICAL preemption, auction bidding
13. Conflict Resolution — policy rules, hierarchical authority, negotiation, Nash equilibrium, audit trail
14. Formation Control — local neighbor offsets, proportional controller, obstacle cascade, self-repair
