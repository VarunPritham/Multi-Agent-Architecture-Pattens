# Agent Router Pattern
## Intent-Based Routing

---

## What Problem Does This Solve?

In a system with many specialized agents, how do you map a user's messy natural language request to the right agent — without hardcoding `if "sales" in query`?

Keyword matching breaks because:
- "Show me revenue numbers" has no keyword match for a SalesAgent
- "Delete all invoices" might accidentally match a FinanceAgent
- Adding a 10th agent requires touching the routing logic everywhere

The Agent Router solves this by introducing a dedicated layer that separates **understanding intent** from **deciding who handles it**.

---

## The Two-Step Architecture

```
Raw user query
      │
      ▼
┌─────────────────────────┐
│  Step 1: Intent         │  ← LLM call (expensive, but only once)
│  Extraction             │
│                         │
│  "Where is Q3 audit?"   │
│         ↓               │
│  { action: "find",      │
│    resource: "document",│
│    params: {period: Q3} │
│    confidence: 0.92 }   │
└─────────────────────────┘
      │
      ▼
┌─────────────────────────┐
│  Step 2: Graph-         │  ← Dict lookup (instant, zero LLM)
│  Constrained Routing    │
│                         │
│  ("find", "document")   │
│         ↓               │
│  → ComplianceAgent ✓    │
└─────────────────────────┘
      │
      ▼
   Dispatch
```

The LLM's job ends at Step 1. It never names an agent — it only produces a structured intent object. Whether that intent maps to an agent is decided by a whitelist you control completely.

---

## The Vocabulary — Goldilocks Abstraction

The most important design decision is the `ActionType` and `ResourceType` enum values.

**Too granular** (bad):
```python
ActionType = Literal["findPDF", "findWordDoc", "findExcel", "findEmail"]
```
The capability graph explodes. Maintenance nightmare.

**Too broad** (bad):
```python
ActionType = Literal["doWork", "getStuff"]
```
The router can't distinguish between agents. Useless.

**Just right** (10–20 canonical terms):
```python
ActionType  = Literal["find", "analyze", "create", "summarize", "delete"]
ResourceType = Literal["sales_report", "document", "invoice", "server_log", "alert"]
```

The goal: each (action, resource) pair maps unambiguously to one agent.

---

## The Capability Graph — The Whitelist

```python
capability_graph = {
    ("find",    "sales_report"):  "SalesAgent",
    ("analyze", "sales_report"):  "SalesAgent",
    ("find",    "document"):      "ComplianceAgent",
    ("create",  "server_log"):    "DevOpsAgent",
    ("analyze", "invoice"):       "FinanceAgent",
}
```

**Properties:**
- If a tuple isn't here, the request is **physically rejected** — not silently ignored
- Adding a new agent = one new line. Zero other changes.
- This is the security boundary. `delete + database` cannot be routed unless explicitly listed.

**Safety guarantee:** The graph acts as a whitelist. The router cannot send a "delete database" command to any agent unless `("delete", "database")` is explicitly in the graph.

---

## Intent Extraction — Why tool_use, Not Prompting

Bad approach:
```
Prompt: "Return JSON with action and resource..."
Response: "Sure! Here's the JSON: ```json\n{...}```"
```
Now you're parsing markdown, handling formatting variations, catching JSON errors.

Good approach:
```python
tool_choice={"type": "tool", "name": "extract_routing_intent"}
```
The API enforces the schema. The response is always a clean dict. No parsing errors.

**Always use tool_use / function calling for structured extraction.**

---

## Semantic Cache

For repeated queries, the LLM call is unnecessary overhead:

```
Query: "Show me the sales report"  →  LLM call  →  cache result
Query: "Show me the sales report"  →  cache HIT  →  skip LLM
```

In production: embed the query → vector DB similarity search. Semantically similar (not just identical) queries hit the cache.

Implementation:
```python
cache_key = hashlib.md5(query.lower().strip().encode()).hexdigest()
if cache_key in self._cache:
    return self._cache[cache_key]
# ... LLM call ...
self._cache[cache_key] = intent
```

---

## Confidence Gating

The LLM's self-reported confidence is useful:

```python
if intent.confidence < 0.6:
    return "Cannot safely route — please rephrase"
```

Below 60% confidence, it's better to ask for clarification than to route incorrectly.

---

## Pros and Cons

### Pros
- **Decoupling**: extraction layer doesn't know agent names; agents don't parse language
- **Scalability**: new agent = one graph entry; routing logic never changes
- **Safety**: graph is a whitelist; impossible to route to unlisted capabilities

### Cons
- **Latency**: LLM call before any real work starts (mitigated by semantic cache)
- **Schema rigidity**: if a user asks something outside the vocabulary, extraction degrades

---

## When to Use

✅ Use when:
- You have 3+ specialized agents with distinct capabilities
- Users interact via natural language
- You need safety guarantees (no agent should receive out-of-scope commands)
- The set of agent capabilities is reasonably stable

❌ Avoid when:
- You have 1–2 agents (overkill, just use if/else)
- Agent capabilities are highly dynamic or constantly changing
- Latency is critical and you can't cache

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `router.py` | Full implementation — vocabulary, capability graph, LLM extraction, cache, safety rejection |

---

## Connection to Other Patterns

The Agent Router is the **"Hello World" of agentic coordination** — it's the entry point into all other patterns. Once a request is routed to an agent, that agent might itself be:
- A **Supervisor** that orchestrates sub-agents
- A **Swarm** of peers processing in parallel
- A **Blackboard** where specialists converge on an answer
