Create a new Tool Routing implementation for the following domain: $ARGUMENTS

Follow the Tool Routing pattern exactly:

**Step 1 — Define ToolDefinition dataclass and ToolRegistry**
- `ToolDefinition`: name, description, agent_id, category, parameters (dict), mock_fn (Callable, repr=False, default=None)
  - `execute(**kwargs) → str` method: calls mock_fn if present, else returns placeholder
- `ToolRegistry`:
  - `register(tool) → None`
  - `tools_for(agent_id) → list[ToolDefinition]`
  - `categories() → list[str]` — sorted unique categories
  - `agent_for_category(category) → Optional[str]`
  - `routing_context() → str` — auto-generated plain-text: category → list of "tool_name: description"

**Step 2 — Define RoutingDecision dataclass**
- Fields: `category`, `target_agent`, `confidence` (float), `reasoning`, `query`

**Step 3 — Build WorkerAgent base + minimum 4 domain specialists**
- `WorkerAgent.__init__(agent_id, registry)`:
  - `self._tools = {t.name: t for t in registry.tools_for(agent_id)}`
- `process(query) → tuple[str, str, float]` — (tool_name, result, duration_seconds)
- `_llm_select_tool`: tool_use with `enum: list(self._tools.keys())`
- `_mock_select_tool`: keyword-based, subclass override
- Each specialist: 3 tools minimum, domain-appropriate keyword rules

**Step 4 — Build RouterAgent**
- LLM path: `classify_intent` tool_use with `enum: registry.categories() + ["unknown"]` and `registry.routing_context()` in prompt
- Mock path: keyword rules → `registry.agent_for_category(cat)` → fallback `RoutingDecision("unknown", "none", 0.10, ...)`

**Step 5 — Build CentralOrchestrator**
- `handle(query)`: classify → check unknown → delegate → print trace → return result
- UNKNOWN path: `"I don't have an agent capable of handling that request."`

**Step 6 — Mock functions + _register_all_tools(registry)**
- One mock fn per tool (min 12), accepting `**kwargs`, extracting `query = kwargs.get("query", "")`
- All registrations in one `_register_all_tools` function

**Step 7 — Three demos**
- Demo 1: Happy path — 6+ queries, all 4 agents exercised
- Demo 2: UNKNOWN fallback — 3 out-of-scope queries
- Demo 3: Registry inspection — print routing_context() and agent tool scopes

**Trace format:**
```
  ┌─ Query: <query>
  │  Router → <category>  (<conf>% conf)
  │  Reason: <reasoning>
  │  → <AgentName>  scoped tools: [tool1, tool2, ...]
  │  Tool selected: <tool_name>  (<Xms>)
  └─ <result preview, newlines → |, max 110 chars>
```

**UNKNOWN trace:**
```
  ┌─ Query: <query>
  │  Router → unknown  (10% conf)
  │  Reason: No category matched
  └─ UNROUTABLE: I don't have an agent capable of handling that request.
```

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/tool_routing_<domain>.py
