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
```

**Scaffold new patterns** — slash commands in `.claude/commands/` let you generate a new implementation for any domain:
```
/create-agent-router        <your domain>
/create-supervisor          <your domain>
/create-swarm               <your domain>
/create-blackboard          <your domain>
/create-supervision-tree    <your domain>
```

---

## Suggested Order

1. Agent Router — understand intent extraction and routing before anything else
2. Supervisor — learn centralized control, checkpointing, structured handoffs
3. Swarm — contrast with Supervisor; understand pull-based, emergent coordination
4. Blackboard — iterative knowledge convergence for ill-defined problems
5. Contract-Net — market-based dynamic agent selection at runtime
6. Supervision Tree — fault isolation and least-privilege capability guarding
