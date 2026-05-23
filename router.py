"""
Agent Router Pattern — Complete Example
---------------------------------------
Demonstrates:
  1. Vocabulary definition (ActionType + ResourceType enums)
  2. Intent extraction via Anthropic tool_use (enforces strict JSON schema)
  3. Capability graph (the routing whitelist)
  4. Graph-constrained routing with safety rejection
  5. Agent dispatch + execution simulation
  6. Semantic cache concept (in-memory hash for repeat queries)
"""

import anthropic
import hashlib
import json
from pydantic import BaseModel
from typing import Literal

# ─────────────────────────────────────────────────────────────
# 1. VOCABULARY — The "language" the entire system speaks.
#    ~10-20 actions/resources is the Goldilocks zone.
# ─────────────────────────────────────────────────────────────

ActionType = Literal["find", "analyze", "create", "delete", "summarize"]
ResourceType = Literal["sales_report", "server_log", "document", "invoice", "alert"]


class RoutingIntent(BaseModel):
    action: ActionType
    resource: ResourceType
    parameters: dict
    confidence: float  # LLM's self-reported confidence (0.0 - 1.0)


# ─────────────────────────────────────────────────────────────
# 2. SPECIALIZED AGENTS — Each knows one domain deeply.
#    In production these would be full agent classes with tools.
# ─────────────────────────────────────────────────────────────

class BaseAgent:
    name: str

    def run(self, params: dict) -> str:
        raise NotImplementedError


class SalesAgent(BaseAgent):
    name = "SalesAgent"

    def run(self, params: dict) -> str:
        period = params.get("period", "latest")
        region = params.get("region", "global")
        return (
            f"[SalesAgent] Fetched sales report | period={period}, region={region}\n"
            f"  → Revenue: $4.2M | Growth: +12% QoQ | Top product: Widget Pro"
        )


class ComplianceAgent(BaseAgent):
    name = "ComplianceAgent"

    def run(self, params: dict) -> str:
        doc_type = params.get("type", "general")
        period = params.get("period", "latest")
        return (
            f"[ComplianceAgent] Retrieved document | type={doc_type}, period={period}\n"
            f"  → Audit status: PASSED | Last reviewed: 2026-04-15 | Findings: 2 minor"
        )


class DevOpsAgent(BaseAgent):
    name = "DevOpsAgent"

    def run(self, params: dict) -> str:
        service = params.get("service", "unknown")
        severity = params.get("severity", "info")
        return (
            f"[DevOpsAgent] Server log created | service={service}, severity={severity}\n"
            f"  → Log ID: LOG-20260523-887 | Stored to: /var/logs/ops/"
        )


class FinanceAgent(BaseAgent):
    name = "FinanceAgent"

    def run(self, params: dict) -> str:
        invoice_id = params.get("invoice_id", "unknown")
        return (
            f"[FinanceAgent] Invoice analysis complete | id={invoice_id}\n"
            f"  → Amount: $12,400 | Status: Pending | Due: 2026-06-01"
        )


# Agent registry — name → instance
AGENT_REGISTRY: dict[str, BaseAgent] = {
    "SalesAgent": SalesAgent(),
    "ComplianceAgent": ComplianceAgent(),
    "DevOpsAgent": DevOpsAgent(),
    "FinanceAgent": FinanceAgent(),
}


# ─────────────────────────────────────────────────────────────
# 3. AGENT ROUTER
# ─────────────────────────────────────────────────────────────

class AgentRouter:

    def __init__(self):
        # The Capability Graph — the source of truth whitelist.
        # Key: (action, resource) | Value: agent name
        # To add a new agent: just add entries here. Zero other changes needed.
        self.capability_graph: dict[tuple, str] = {
            ("find",      "sales_report"):  "SalesAgent",
            ("analyze",   "sales_report"):  "SalesAgent",
            ("summarize", "sales_report"):  "SalesAgent",
            ("find",      "document"):      "ComplianceAgent",
            ("summarize", "document"):      "ComplianceAgent",
            ("create",    "server_log"):    "DevOpsAgent",
            ("analyze",   "server_log"):    "DevOpsAgent",
            ("find",      "alert"):         "DevOpsAgent",
            ("analyze",   "invoice"):       "FinanceAgent",
            ("find",      "invoice"):       "FinanceAgent",
        }

        # Semantic cache: query_hash → RoutingIntent
        # In production: embed query → vector DB similarity search
        self._cache: dict[str, RoutingIntent] = {}

        self._client = anthropic.Anthropic()

    # ── Step 1: Intent Extraction ───────────────────────────

    def extract_intent(self, user_query: str) -> RoutingIntent:
        """
        Uses Anthropic tool_use to force structured JSON output.
        tool_use = function calling — eliminates free-text parsing errors.
        Falls back to mock extraction if no API key is available (demo mode).
        """
        # Check semantic cache first (hash as a stand-in for embedding similarity)
        cache_key = hashlib.md5(user_query.lower().strip().encode()).hexdigest()
        if cache_key in self._cache:
            print(f"  [Cache HIT] Skipping LLM extraction for cached query")
            return self._cache[cache_key]

        import os
        if not os.environ.get("ANTHROPIC_API_KEY"):
            intent = self._mock_extract(user_query)
        else:
            intent = self._llm_extract(user_query)

        self._cache[cache_key] = intent
        return intent

    def _llm_extract(self, user_query: str) -> RoutingIntent:
        """Real extraction via Anthropic tool_use (enforces strict JSON schema)."""
        tool_definition = {
            "name": "extract_routing_intent",
            "description": (
                "Extract the user's intent as a structured action + resource pair. "
                "Only use the allowed action and resource values."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["find", "analyze", "create", "delete", "summarize"],
                        "description": "The verb — what the user wants to DO"
                    },
                    "resource": {
                        "type": "string",
                        "enum": ["sales_report", "server_log", "document", "invoice", "alert"],
                        "description": "The noun — what the user wants to act ON"
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Additional context extracted from the query (period, region, id, etc.)"
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Your confidence in this extraction, 0.0 to 1.0"
                    }
                },
                "required": ["action", "resource", "parameters", "confidence"]
            }
        }

        response = self._client.messages.create(
            model="claude-haiku-4-5-20251001",  # Fast + cheap for routing layer
            max_tokens=256,
            tools=[tool_definition],
            tool_choice={"type": "tool", "name": "extract_routing_intent"},
            messages=[{
                "role": "user",
                "content": (
                    f"Extract the routing intent from this user query:\n\n\"{user_query}\"\n\n"
                    f"Map it to the closest matching action and resource from the allowed values."
                )
            }]
        )

        tool_use_block = next(b for b in response.content if b.type == "tool_use")
        extracted = tool_use_block.input
        return RoutingIntent(
            action=extracted["action"],
            resource=extracted["resource"],
            parameters=extracted.get("parameters", {}),
            confidence=extracted.get("confidence", 1.0)
        )

    def _mock_extract(self, user_query: str) -> RoutingIntent:
        """
        Demo-mode extraction — mimics what the LLM would return.
        In production this entire method is replaced by _llm_extract().
        The routing logic below is 100% identical either way.
        """
        print(f"  [DEMO MODE] Simulating LLM intent extraction (no API key)")
        q = user_query.lower()

        # Simulate semantic understanding (not keyword matching — note how
        # "breakdown of APAC sales" → find+sales_report, not a keyword hit)
        mock_table = [
            # Destructive verbs checked FIRST — more specific wins over noun-only match
            (["delete", "remove", "purge"],                              "delete",   "invoice",      {}),
            (["audit", "security", "compliance", "q3 finance"],          "find",     "document",    {"type": "audit", "period": "Q3"}),
            (["sales", "revenue", "performance", "apac", "quarter"],     "find",     "sales_report", {"region": "APAC", "period": "last quarter"}),
            (["log", "error", "critical", "server", "service"],          "create",   "server_log",   {"service": "payments", "severity": "critical"}),
            (["invoice", "inv-", "bill", "payment due"],                 "analyze",  "invoice",      {"invoice_id": "INV-2024-441"}),
            (["summarize", "summary", "overview", "sales"],              "summarize","sales_report",  {}),
        ]

        for keywords, action, resource, params in mock_table:
            if any(kw in q for kw in keywords):
                return RoutingIntent(action=action, resource=resource, parameters=params, confidence=0.92)

        # Unknown intent
        return RoutingIntent(action="find", resource="document", parameters={}, confidence=0.3)

    # ── Step 2: Graph-Constrained Routing ──────────────────

    def route_request(self, user_query: str) -> str:
        print(f"\n{'='*60}")
        print(f"  Query: \"{user_query}\"")
        print(f"{'='*60}")

        # Step 1: Extract intent
        print(f"\n[Step 1] Extracting intent...")
        intent = self.extract_intent(user_query)
        print(f"  → action:     {intent.action}")
        print(f"  → resource:   {intent.resource}")
        print(f"  → parameters: {intent.parameters}")
        print(f"  → confidence: {intent.confidence:.0%}")

        # Low-confidence guard
        if intent.confidence < 0.6:
            return (
                f"\n[ROUTER] Low confidence ({intent.confidence:.0%}). "
                f"Cannot safely route. Please rephrase your request."
            )

        # Step 2: Graph lookup
        print(f"\n[Step 2] Looking up capability graph...")
        key = (intent.action, intent.resource)
        agent_name = self.capability_graph.get(key)

        if not agent_name:
            # Safety: hard rejection — not a graceful fallback, an explicit block
            registered = [f"({a},{r})" for (a, r) in self.capability_graph]
            return (
                f"\n[ROUTER] REJECTED — No agent registered for "
                f"({intent.action}, {intent.resource}).\n"
                f"  Registered capabilities: {', '.join(registered)}"
            )

        print(f"  → Matched: ({intent.action}, {intent.resource}) → {agent_name} ✓")

        # Step 3: Dispatch
        print(f"\n[Step 3] Dispatching to {agent_name}...")
        agent = AGENT_REGISTRY[agent_name]
        result = agent.run(intent.parameters)

        return f"\n[RESULT]\n{result}"


# ─────────────────────────────────────────────────────────────
# 4. DEMO — Run several queries to see routing in action
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    router = AgentRouter()

    queries = [
        # ✓ Routes to ComplianceAgent
        "Where is the latest security audit for the Q3 finance project?",

        # ✓ Routes to SalesAgent
        "Give me a breakdown of APAC sales performance last quarter",

        # ✓ Routes to DevOpsAgent
        "I need to log a critical error for the payments service",

        # ✓ Routes to FinanceAgent
        "Can you analyze invoice #INV-2024-441?",

        # ✗ Should be REJECTED — "delete" + "invoice" not in graph
        "Delete all invoices from last year",

        # ✓ Cache demo — same query as #1, should skip LLM
        "Where is the latest security audit for the Q3 finance project?",
    ]

    for query in queries:
        result = router.route_request(query)
        print(result)
