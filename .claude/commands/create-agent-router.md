Create a new Agent Router implementation for the following domain: $ARGUMENTS

Follow the Agent Router pattern exactly:

**Step 1 — Define the vocabulary**
- Define `ActionType` as a `Literal` with 10–20 canonical verbs appropriate to the domain
- Define `ResourceType` as a `Literal` with 10–20 canonical nouns appropriate to the domain
- Create a `RoutingIntent` Pydantic model with fields: action, resource, parameters (dict), confidence (float)

**Step 2 — Build the capability graph**
- Create a dict mapping `(action, resource)` tuples → agent name strings
- Include at least 6 entries covering 3 different agent types
- Each agent should own 2–3 capability tuples

**Step 3 — Implement intent extraction**
- Use Anthropic tool_use (not prompt engineering) to enforce strict schema output
- Use `claude-haiku-4-5-20251001` — fast and cheap for routing
- Include a semantic cache using MD5 hash of normalized query
- Include mock fallback mode when `ANTHROPIC_API_KEY` is not set

**Step 4 — Implement routing**
- Graph lookup: `key = (intent.action, intent.resource)`
- Safety check: if key not in graph → hard reject with list of registered capabilities
- Confidence check: reject if confidence < 0.6
- Dispatch: look up agent from a registry dict, call `.run(params)`

**Step 5 — Build agent stubs**
- Create a stub class for each agent in the capability graph
- Each has a `run(params: dict) → str` method
- Stub methods should return realistic-looking output for the domain

**Step 6 — Demo**
- Include 5–6 example queries in `if __name__ == "__main__":`
  - 2–3 that route successfully to different agents
  - 1 that gets rejected (unsupported capability)
  - 1 that hits the cache (repeat of a previous query)

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/agent_router_<domain>.py
