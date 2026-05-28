# Tool Routing in Multi-Agent Contexts
## Scoped Tool Dispatch + Dynamic Registry

---

## What Problem Does This Solve?

In a naive multi-agent system with many agents and many tools, every agent can see every tool. This causes three failure modes:

1. **Misuse** — WeatherAgent accidentally invokes `search_flights` because it sounded relevant
2. **Hallucination** — an agent asked about flight prices fabricates an answer rather than failing cleanly, because it knows a flight tool exists somewhere in the system
3. **Decision fatigue** — when an LLM must choose among 20+ tools, accuracy drops compared to choosing among 3

Tool Routing fixes all three by scoping visibility: each agent is instantiated with **only the tools registered for its domain**. An agent cannot invoke a tool it cannot see.

---

## How This Differs From the Agent Router

The Agent Router (Pattern #1) routes at the **intent level** — it extracts an `(action, resource)` pair from natural language and maps it to an agent via a capability graph.

Tool Routing operates at the **tool level** and adds two new mechanisms:

| Dimension | Agent Router | Tool Routing |
|---|---|---|
| Routing source | Capability graph (hardcoded) | ToolRegistry (dynamic, self-populating) |
| What gets routed | Intent → Agent | Intent → Agent → Tool (two levels) |
| Agent tool visibility | Not explicitly scoped | Scoped at instantiation — agent only sees its tools |
| Adding a new agent | Requires code change in router | Register tools in registry → router adapts automatically |

The distinction matters at scale: when you have 50 tools across 10 agents, a dynamic registry that auto-generates routing context is essential. Hardcoded maps become maintenance liabilities.

---

## The ToolRegistry — Single Source of Truth

The ToolRegistry is the foundation of the pattern. Agents register their tools once; everything else is derived from it.

```python
class ToolRegistry:
    def register(self, tool: ToolDefinition) → None
    def tools_for(self, agent_id: str) → list[ToolDefinition]
    def categories(self) → list[str]
    def agent_for_category(self, category: str) → Optional[str]
    def routing_context(self) → str    # auto-generated LLM prompt context
```

The critical method is `routing_context()`:

```python
def routing_context(self) -> str:
    by_cat = {}
    for t in self._tools.values():
        by_cat.setdefault(t.category, []).append(f"{t.name}: {t.description}")
    lines = []
    for cat, descs in sorted(by_cat.items()):
        lines.append(f"  {cat}:")
        for d in descs:
            lines.append(f"    - {d}")
    return "\n".join(lines)
```

When a new agent registers its tools, `routing_context()` automatically includes them the next time the RouterAgent classifies a request. **No code changes needed in the router.**

---

## Two-Level Routing — The Core Mechanism

Every request passes through two routing decisions:

```
User: "Is it going to rain in London tomorrow?"
        ↓
[Level 1 — RouterAgent]
  Classifies intent → weather_query  (91% confidence)
  Maps category → WeatherAgent
        ↓
[Level 2 — WeatherAgent]
  Receives query, inspects its scoped toolset:
    [get_current_weather, get_forecast, get_weather_alerts]
  Selects → get_forecast  ("tomorrow" keyword → forecast tool)
        ↓
[ToolDefinition.execute()]
  Returns: "5-Day Forecast — London: Mon ☁ Cloudy 14°C/9°C | ..."
```

The WeatherAgent never knew `get_stock_price` existed. The FinancialAgent never knew `search_flights` existed. Scoping is enforced structurally.

---

## Scoping at Instantiation — The Key Invariant

The scoping happens once, in `__init__`:

```python
class WorkerAgent:
    def __init__(self, agent_id: str, registry: ToolRegistry):
        self.agent_id = agent_id
        self._tools = {t.name: t for t in registry.tools_for(agent_id)}
        # After this line, self._tools is the agent's entire tool universe.
        # It is never updated. It never receives tools from other agents.
```

When the LLM performs tool selection within an agent, the schema enum is built from `list(self._tools.keys())`. The LLM is structurally prevented from naming a tool outside the agent's scope — not by instruction, but by the schema definition.

```python
def _llm_select_tool(self, query: str) -> ToolDefinition:
    select_schema = {
        "name": "select_tool",
        "input_schema": {
            "properties": {
                "tool_name": {
                    "type": "string",
                    "enum": list(self._tools.keys()),  # ← structurally scoped
                }
            }
        }
    }
    # LLM cannot output a tool_name not in this enum
```

This is stronger than prompt-level restrictions ("don't use tools outside your domain") because it cannot be overridden by prompt injection or unexpected outputs.

---

## The UNKNOWN Category — First-Class Fallback

Every classification has five possible outcomes:

| Outcome | Handling |
|---|---|
| `financial_query` | Route to FinancialAgent |
| `weather_query` | Route to WeatherAgent |
| `travel_query` | Route to TravelAgent |
| `calendar_query` | Route to CalendarAgent |
| `unknown` | Return clean error message |

`unknown` is not an error state — it's a designed outcome. The alternative (force-routing an unclassifiable request to the "closest" agent) causes the agent to misuse its tools.

```python
if decision.category == "unknown":
    return "I don't have an agent capable of handling that request."
```

The user receives a clear, honest response. No agent is coerced into fabricating an answer.

---

## LLM Classification — The Router's Prompt

When using a real LLM, the RouterAgent passes the full registry context to the classification prompt:

```python
resp = client.messages.create(
    tools=[classify_schema],
    tool_choice={"type": "tool", "name": "classify_intent"},
    messages=[{
        "role": "user",
        "content": (
            f"Available routing categories and their tools:\n"
            f"{self.registry.routing_context()}\n\n"  # ← dynamic, from registry
            f"Request: '{query}'\n\n"
            f"Classify into one of: {', '.join(categories)}. "
            f"Use 'unknown' if no category fits."
        )
    }]
)
```

The LLM sees not just category names but tool descriptions — so it can make an informed routing decision even for ambiguous queries. If the user asks "Can you check my holdings?", the LLM sees that `get_portfolio_summary` exists in `financial_query` and routes correctly.

---

## Mock Mode — No API Key Required

Every tool has a `mock_fn` registered alongside its schema. The `USE_LLM` flag controls which path runs:

```python
USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))
```

Without a key:
- RouterAgent uses keyword rules to classify intent
- WorkerAgents use keyword rules to select tools
- ToolDefinition.execute() calls mock_fn directly

With a key:
- RouterAgent uses `classify_intent` tool_use with full registry context
- WorkerAgents use `select_tool` tool_use with scoped enum
- Mock functions still execute (no real APIs called)

The architecture is identical in both modes — only the decision-making changes.

---

## Adding a New Agent — Zero Router Changes

The payoff of the dynamic registry becomes clear when adding a new domain:

```python
# 1. Write mock functions
def _mock_get_news_headlines(**kwargs) -> str: ...
def _mock_search_articles(**kwargs) -> str: ...
def _mock_summarise_topic(**kwargs) -> str: ...

# 2. Write the agent class
class NewsAgent(WorkerAgent):
    def _mock_select_tool(self, query: str) -> Optional[ToolDefinition]:
        if any(w in query.lower() for w in ["headline", "breaking"]):
            return self._tools.get("get_news_headlines")
        ...

# 3. Register the tools
registry.register(ToolDefinition("get_news_headlines", "...", "NewsAgent", "news_query", {}, _mock_get_news_headlines))
# ... (3 more)

# 4. Instantiate the agent
agents["NewsAgent"] = NewsAgent("NewsAgent", registry)
```

That's it. The `RouterAgent` now includes `news_query` in its classification enum automatically because `registry.categories()` includes it. The LLM prompt includes news tool descriptions. No `if/elif` chains to update.

---

## Comparison: Tool Routing vs Other Patterns

| Pattern | Routing source | Tool scoping | Dynamic? |
|---|---|---|---|
| Agent Router | Hardcoded capability graph | None — agents choose their own tools | Requires code change |
| Supervisor | Hardcoded workflow | N/A — supervisor orchestrates directly | No |
| Swarm | Self-selection from shared board | None | Partially (agents pick tasks) |
| **Tool Routing** | **Dynamic ToolRegistry** | **Scoped at agent instantiation** | **Yes — register once, adapt automatically** |

---

## Pros and Cons

### Pros
- **Higher accuracy**: scoped tools reduce incorrect invocation — fewer distractors
- **No hallucination on unknown**: UNKNOWN category prevents forced misuse
- **Dynamic extensibility**: add agents by registering tools — no router code changes
- **Structural enforcement**: enum-based tool_use schema prevents out-of-scope selection
- **Separation of concerns**: routing logic (router) is separate from execution logic (agents)

### Cons
- **Rigidity**: if a task genuinely requires tools from two different agents, the pattern has no native path — requires a supervisor layer or tool composition
- **Cold categories**: a category with no registered tools breaks routing silently
- **Upfront design**: agent boundaries and category definitions must be designed carefully before implementation; poor boundaries cause routing errors that are hard to debug

---

## When to Use

✅ Use when:
- You have 4+ specialized agents with non-overlapping tool domains
- Tool misuse (wrong agent using wrong tool) is a known failure mode
- You need to add new agents without touching existing routing code
- The same query pattern must always hit the same agent

❌ Avoid when:
- Tasks regularly require tools from multiple domains (use Supervisor instead)
- You have only 1-2 agents — the registry overhead isn't justified
- All agents need access to all tools — there's nothing to scope

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `tool_routing.py` | Personal assistant — 4 agents (Financial, Weather, Travel, Calendar), 12 tools, dynamic ToolRegistry, LLM + mock routing, UNKNOWN fallback, registry inspection |

---

## Real-World Equivalents

- **Hospital triage**: a triage nurse (router) directs a patient to cardiology, orthopaedics, or neurology — each department has only its own equipment (scoped tools)
- **Customer support IVR**: classifies the call as billing, technical, or sales — routes to the relevant team; the billing team doesn't have access to technical diagnostic tools
- **Enterprise API gateway**: routes requests to microservices by path prefix — each service exposes only its own endpoints
- **Law firm intake**: classifies a matter as corporate, litigation, or tax — assigns to the practice group; a tax associate doesn't have access to litigation research tools
