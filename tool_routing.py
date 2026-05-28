"""
Tool Routing in Multi-Agent Contexts — Scoped Tool Dispatch
------------------------------------------------------------
Demonstrates:
  1. ToolRegistry — agents self-register capabilities; router queries dynamically
  2. Scoped tools — each specialist receives ONLY its own tools (no cross-contamination)
  3. RouterAgent — classifies intent via LLM tool_use; routes to the correct specialist
  4. Two-level routing: Router→Agent (which specialist?) + Agent→Tool (which of my tools?)
  5. UNKNOWN fallback — unroutable queries get a clear message, not a hallucinated answer
  6. Mock mode (no API key) + LLM mode (full tool_use intent classification)

Scenario: Intelligent personal assistant
  FinancialAgent  — stock prices, portfolio, market news
  WeatherAgent    — current weather, forecasts, storm alerts
  TravelAgent     — flight search, hotel search, travel advisories
  CalendarAgent   — daily schedule, event creation, availability lookup

Key distinction from Agent Router:
  Agent Router routes by intent (action, resource) → agent.
  Tool Routing routes by tool availability — registry is the source of truth,
  and each agent does a second-level routing decision within its scoped toolset.
"""

import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Callable
import anthropic


USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))
client  = anthropic.Anthropic() if USE_LLM else None


# ─────────────────────────────────────────────────────────────
# 1. TOOL REGISTRY — The dynamic capability map
# ─────────────────────────────────────────────────────────────

@dataclass
class ToolDefinition:
    name:        str
    description: str
    agent_id:    str
    category:    str
    parameters:  dict
    mock_fn:     Optional[Callable] = field(repr=False, default=None)

    def execute(self, **kwargs) -> str:
        if self.mock_fn:
            return self.mock_fn(**kwargs)
        return f"[{self.name}] executed with {kwargs}"


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def tools_for(self, agent_id: str) -> list[ToolDefinition]:
        return [t for t in self._tools.values() if t.agent_id == agent_id]

    def categories(self) -> list[str]:
        return sorted(set(t.category for t in self._tools.values()))

    def agent_for_category(self, category: str) -> Optional[str]:
        for t in self._tools.values():
            if t.category == category:
                return t.agent_id
        return None

    def routing_context(self) -> str:
        """Plain-text summary of all categories and tools — passed to the RouterAgent LLM."""
        by_cat: dict[str, list[str]] = {}
        for t in self._tools.values():
            by_cat.setdefault(t.category, []).append(f"{t.name}: {t.description}")
        lines = []
        for cat, descs in sorted(by_cat.items()):
            lines.append(f"  {cat}:")
            for d in descs:
                lines.append(f"    - {d}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# 2. ROUTING DECISION — Structured output from RouterAgent
# ─────────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    category:     str
    target_agent: str
    confidence:   float
    reasoning:    str
    query:        str


# ─────────────────────────────────────────────────────────────
# 3. WORKER AGENTS — Each knows ONLY its own tools
# ─────────────────────────────────────────────────────────────

class WorkerAgent:
    def __init__(self, agent_id: str, registry: ToolRegistry):
        self.agent_id = agent_id
        # Scoped: instantiated with only the tools registered for this agent
        self._tools: dict[str, ToolDefinition] = {
            t.name: t for t in registry.tools_for(agent_id)
        }

    def process(self, query: str) -> tuple[str, str, float]:
        """Returns (tool_name, result, duration_seconds)."""
        tool = self._select_tool(query)
        if tool is None:
            return ("none", f"No matching tool in {self.agent_id}'s toolset", 0.0)
        t0 = time.time()
        result = tool.execute(query=query)
        return (tool.name, result, time.time() - t0)

    def _select_tool(self, query: str) -> Optional[ToolDefinition]:
        if USE_LLM and client:
            return self._llm_select_tool(query)
        return self._mock_select_tool(query)

    def _llm_select_tool(self, query: str) -> Optional[ToolDefinition]:
        if not self._tools:
            return None
        select_schema = {
            "name": "select_tool",
            "description": "Choose the best tool from the available set for this query",
            "input_schema": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "enum": list(self._tools.keys()),
                        "description": "The tool to invoke"
                    }
                },
                "required": ["tool_name"]
            }
        }
        descriptions = "\n".join(
            f"  - {t.name}: {t.description}" for t in self._tools.values()
        )
        resp = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=128,
            tools=[select_schema],
            tool_choice={"type": "tool", "name": "select_tool"},
            messages=[{
                "role": "user",
                "content": f"Available tools:\n{descriptions}\n\nQuery: {query}\n\nSelect the best tool."
            }]
        )
        for block in resp.content:
            if block.type == "tool_use":
                return self._tools.get(block.input.get("tool_name", ""))
        return list(self._tools.values())[0]

    def _mock_select_tool(self, query: str) -> Optional[ToolDefinition]:
        raise NotImplementedError


class FinancialAgent(WorkerAgent):
    def _mock_select_tool(self, query: str) -> Optional[ToolDefinition]:
        q = query.lower()
        if any(w in q for w in ["news", "headline", "latest", "sector", "market update"]):
            return self._tools.get("get_market_news")
        if any(w in q for w in ["portfolio", "holdings", "worth", "positions", "p&l"]):
            return self._tools.get("get_portfolio_summary")
        if any(w in q for w in ["stock", "price", "share", "ticker", "trading at"]):
            return self._tools.get("get_stock_price")
        return self._tools.get("get_market_news")


class WeatherAgent(WorkerAgent):
    def _mock_select_tool(self, query: str) -> Optional[ToolDefinition]:
        q = query.lower()
        if any(w in q for w in ["forecast", "tomorrow", "this week", "next week"]):
            return self._tools.get("get_forecast")
        if any(w in q for w in ["alert", "warning", "storm", "severe"]):
            return self._tools.get("get_weather_alerts")
        return self._tools.get("get_current_weather")


class TravelAgent(WorkerAgent):
    def _mock_select_tool(self, query: str) -> Optional[ToolDefinition]:
        q = query.lower()
        if any(w in q for w in ["hotel", "stay", "accommodation", "room", "lodge"]):
            return self._tools.get("search_hotels")
        if any(w in q for w in ["advisory", "safe", "visa", "restriction"]):
            return self._tools.get("get_travel_advisories")
        return self._tools.get("search_flights")


class CalendarAgent(WorkerAgent):
    def _mock_select_tool(self, query: str) -> Optional[ToolDefinition]:
        q = query.lower()
        if any(w in q for w in ["create", "add", "schedule", "book", "set up", "block"]):
            return self._tools.get("create_event")
        if any(w in q for w in ["free", "available", "availability", "when can", "open slot"]):
            return self._tools.get("find_availability")
        return self._tools.get("get_schedule")


# ─────────────────────────────────────────────────────────────
# 4. ROUTER AGENT — Classifies intent, routes to specialist
# ─────────────────────────────────────────────────────────────

class RouterAgent:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def classify(self, query: str) -> RoutingDecision:
        if USE_LLM and client:
            return self._llm_classify(query)
        return self._mock_classify(query)

    def _llm_classify(self, query: str) -> RoutingDecision:
        categories = self.registry.categories() + ["unknown"]
        classify_schema = {
            "name": "classify_intent",
            "description": "Classify the user request into a routing category",
            "input_schema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": categories,
                        "description": "The category that best matches this request"
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence score 0.0–1.0"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "One sentence explaining the routing decision"
                    }
                },
                "required": ["category", "confidence", "reasoning"]
            }
        }
        resp = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=256,
            tools=[classify_schema],
            tool_choice={"type": "tool", "name": "classify_intent"},
            messages=[{
                "role": "user",
                "content": (
                    f"Available routing categories and their tools:\n"
                    f"{self.registry.routing_context()}\n\n"
                    f"Request: '{query}'\n\n"
                    f"Classify into one of: {', '.join(categories)}. "
                    f"Use 'unknown' if no category fits."
                )
            }]
        )
        for block in resp.content:
            if block.type == "tool_use":
                cat  = block.input.get("category", "unknown")
                conf = float(block.input.get("confidence", 0.5))
                rsn  = block.input.get("reasoning", "")
                return RoutingDecision(cat, self.registry.agent_for_category(cat) or "none", conf, rsn, query)
        return RoutingDecision("unknown", "none", 0.0, "LLM classification failed", query)

    def _mock_classify(self, query: str) -> RoutingDecision:
        q = query.lower()
        rules = [
            (["stock", "price", "share", "market", "portfolio", "nasdaq",
              "earnings", "dividend", "ticker", "s&p", "dow", "invest",
              "trading", "google stock", "apple stock", "fund"],
             "financial_query", 0.93, "Financial keywords detected"),
            (["weather", "temperature", "rain", "snow", "sunny", "cloudy",
              "forecast", "storm", "wind", "humid", "celsius", "fahrenheit",
              "degrees"],
             "weather_query", 0.91, "Weather keywords detected"),
            (["flight", "hotel", "travel", "trip", "vacation", "airport",
              "airline", "fly to", "stay in", "destination", "visa",
              "passport"],
             "travel_query", 0.92, "Travel keywords detected"),
            (["meeting", "calendar", "schedule", "appointment", "event",
              "availability", "agenda", "reminder", "block time", "free slot",
              "meetings"],
             "calendar_query", 0.90, "Calendar keywords detected"),
        ]
        for keywords, cat, conf, reason in rules:
            if any(kw in q for kw in keywords):
                return RoutingDecision(cat, self.registry.agent_for_category(cat), conf, reason, query)
        return RoutingDecision("unknown", "none", 0.10, "No category matched", query)


# ─────────────────────────────────────────────────────────────
# 5. CENTRAL ORCHESTRATOR — Wires everything together
# ─────────────────────────────────────────────────────────────

class CentralOrchestrator:
    def __init__(self):
        self.registry = ToolRegistry()
        _register_all_tools(self.registry)

        self.agents: dict[str, WorkerAgent] = {
            "FinancialAgent": FinancialAgent("FinancialAgent", self.registry),
            "WeatherAgent":   WeatherAgent("WeatherAgent",     self.registry),
            "TravelAgent":    TravelAgent("TravelAgent",       self.registry),
            "CalendarAgent":  CalendarAgent("CalendarAgent",   self.registry),
        }
        self.router = RouterAgent(self.registry)

    def handle(self, query: str) -> str:
        print(f"\n  ┌─ Query: {query}")

        decision = self.router.classify(query)
        print(f"  │  Router → {decision.category}  ({decision.confidence:.0%} conf)")
        print(f"  │  Reason: {decision.reasoning}")

        if decision.category == "unknown" or decision.target_agent == "none":
            resp = "I don't have an agent capable of handling that request."
            print(f"  └─ UNROUTABLE: {resp}")
            return resp

        agent = self.agents.get(decision.target_agent)
        if agent is None:
            resp = f"Agent '{decision.target_agent}' is unavailable."
            print(f"  └─ ERROR: {resp}")
            return resp

        print(f"  │  → {decision.target_agent}  scoped tools: {list(agent._tools.keys())}")
        tool_name, result, dur = agent.process(query)
        print(f"  │  Tool selected: {tool_name}  ({dur * 1000:.0f}ms)")
        preview = result.replace("\n", " | ")[:110]
        print(f"  └─ {preview}")
        return result


# ─────────────────────────────────────────────────────────────
# MOCK TOOL IMPLEMENTATIONS
# ─────────────────────────────────────────────────────────────

def _extract_ticker(query: str) -> str:
    names = {"google": "GOOGL", "alphabet": "GOOGL", "apple": "AAPL",
             "microsoft": "MSFT", "amazon": "AMZN", "tesla": "TSLA",
             "nvidia": "NVDA", "meta": "META"}
    q = query.lower()
    for name, ticker in names.items():
        if name in q:
            return ticker
    m = re.search(r'\b([A-Z]{2,5})\b', query)
    return m.group(1) if m else "GOOGL"


def _mock_get_stock_price(**kwargs) -> str:
    ticker = _extract_ticker(kwargs.get("query", ""))
    data = {
        "GOOGL": ("$182.45", "+1.2%", "28.4", "18.2M"),
        "AAPL":  ("$213.67", "+0.8%", "31.2", "55.1M"),
        "MSFT":  ("$415.23", "+0.5%", "34.7", "22.8M"),
        "AMZN":  ("$192.88", "-0.3%", "62.1", "31.4M"),
        "TSLA":  ("$248.50", "+3.1%", "72.3", "88.7M"),
        "NVDA":  ("$875.40", "+2.7%", "58.9", "41.5M"),
        "META":  ("$502.33", "+1.5%", "26.8", "17.3M"),
    }
    price, change, pe, vol = data.get(ticker, ("$150.00", "+0.0%", "20.0", "10.0M"))
    return f"{ticker}  {price}  {change}  |  P/E: {pe}  Vol: {vol} shares  |  NASDAQ"


def _mock_get_portfolio_summary(**kwargs) -> str:
    return ("Portfolio  (market close):\n"
            "  AAPL  50 sh × $213.67  = $10,683.50  +8.2%\n"
            "  GOOGL 20 sh × $182.45  =  $3,649.00  +3.1%\n"
            "  MSFT  30 sh × $415.23  = $12,456.90  +5.7%\n"
            "  NVDA  10 sh × $875.40  =  $8,754.00 +14.3%\n"
            "  ─────────────────────────────────────────────\n"
            "  Total: $35,543.40  |  Day P&L: +$418.70 (+1.19%)")


def _mock_get_market_news(**kwargs) -> str:
    q = kwargs.get("query", "").lower()
    if "tech" in q:
        return ("Tech Headlines:\n"
                "  • NVDA +2.7% — record AI chip demand; H100 backorders extend to Q3\n"
                "  • MSFT Azure +29% YoY; cloud margins expand to 43%\n"
                "  • AAPL WWDC keynote tomorrow; Vision Pro 2 rumoured\n"
                "  • Fed holds rates — tech sector rallies on pause signal")
    return ("Market Summary:\n"
            "  S&P 500: 5,412  +0.6%  |  Nasdaq: 17,891  +0.9%\n"
            "  10-yr Treasury: 4.21%  |  DXY: 104.3  |  VIX: 13.8\n"
            "  Oil WTI: $78.40/bbl  |  Gold: $2,341/oz\n"
            "  78% of S&P 500 companies beat Q2 estimates")


def _extract_city(query: str) -> str:
    cities = ["london", "new york", "paris", "tokyo", "sydney",
              "chicago", "los angeles", "dubai", "singapore", "berlin"]
    q = query.lower()
    for c in cities:
        if c in q:
            return c.title()
    return "London"


def _mock_get_current_weather(**kwargs) -> str:
    city = _extract_city(kwargs.get("query", ""))
    data = {
        "London":      ("Overcast",      "15°C", "82%", "12 km/h SW"),
        "New York":    ("Partly Cloudy", "24°C", "58%", "18 km/h NW"),
        "Paris":       ("Clear",         "21°C", "45%", "8 km/h N"),
        "Tokyo":       ("Rainy",         "19°C", "91%", "22 km/h E"),
        "Sydney":      ("Sunny",         "17°C", "40%", "15 km/h SE"),
        "Dubai":       ("Hazy",          "38°C", "62%", "10 km/h NE"),
        "Los Angeles": ("Sunny",         "27°C", "35%", "5 km/h W"),
    }
    cond, temp, hum, wind = data.get(city, ("Clear", "20°C", "55%", "10 km/h"))
    return f"{city}: {cond}  {temp}  |  Humidity: {hum}  |  Wind: {wind}  |  UV: 4 (Moderate)"


def _mock_get_forecast(**kwargs) -> str:
    city = _extract_city(kwargs.get("query", ""))
    forecasts = {
        "London": [("Mon", "☁  Cloudy",       "14°C/9°C"),
                   ("Tue", "🌧 Rain",          "11°C/7°C"),
                   ("Wed", "⛅ Part. Cloudy",  "15°C/10°C"),
                   ("Thu", "☀  Sunny",         "18°C/13°C"),
                   ("Fri", "☀  Sunny",         "19°C/13°C")],
        "Paris":  [("Mon", "☀  Sunny",         "22°C/14°C"),
                   ("Tue", "☀  Sunny",         "23°C/15°C"),
                   ("Wed", "⛅ Part. Cloudy",  "20°C/13°C"),
                   ("Thu", "🌦 Showers",       "17°C/11°C"),
                   ("Fri", "☀  Sunny",         "21°C/14°C")],
    }
    days = forecasts.get(city, [
        ("Mon", "☀  Sunny",  "22°C/15°C"), ("Tue", "⛅ Cloudy", "20°C/14°C"),
        ("Wed", "🌧 Rain",   "17°C/12°C"), ("Thu", "☀  Sunny",  "21°C/15°C"),
        ("Fri", "☀  Sunny",  "23°C/16°C"),
    ])
    lines = [f"5-Day Forecast — {city}:"]
    for day, cond, temps in days:
        lines.append(f"  {day}  {cond:<20} {temps}")
    return "\n".join(lines)


def _mock_get_weather_alerts(**kwargs) -> str:
    return ("Active Severe Weather Alerts:\n"
            "  ⚠ YELLOW — Wind: 50–60 mph gusts, Scotland  (Sun 18:00 → Mon 06:00)\n"
            "  ⚠ YELLOW — Rain: 40–60mm/24h, Wales & SW England  (Mon 00:00 → 18:00)\n"
            "  ℹ  No severe alerts for England south of Birmingham")


def _extract_route(query: str) -> tuple[str, str]:
    codes = {"new york": "JFK", "nyc": "JFK", "london": "LHR",
             "los angeles": "LAX", "la ": "LAX", "paris": "CDG",
             "tokyo": "NRT", "dubai": "DXB", "sydney": "SYD",
             "chicago": "ORD", "toronto": "YYZ"}
    q = query.lower()
    found = sorted(
        [(code, q.index(name)) for name, code in codes.items() if name in q],
        key=lambda x: x[1]
    )
    if len(found) >= 2:
        return found[0][0], found[1][0]
    if len(found) == 1:
        return found[0][0], "LHR"
    return "JFK", "LHR"


def _mock_search_flights(**kwargs) -> str:
    origin, dest = _extract_route(kwargs.get("query", ""))
    routes = {
        ("JFK", "LAX"): [("AA 201", "07:00→10:30", "$289", "Nonstop"),
                         ("UA 432", "09:15→12:50", "$312", "Nonstop"),
                         ("DL 567", "14:00→17:40", "$275", "Nonstop")],
        ("JFK", "LHR"): [("BA 178", "22:00→10:15+1", "$654", "Nonstop"),
                         ("AA 101", "17:45→06:00+1", "$712", "Nonstop"),
                         ("VS 025", "20:55→09:10+1", "$589", "Nonstop")],
        ("JFK", "CDG"): [("AF 011", "19:00→08:30+1", "$521", "Nonstop"),
                         ("DL 263", "23:55→12:30+1", "$487", "Nonstop")],
    }
    flights = routes.get((origin, dest),
                         [("BA 001", "08:00→14:30", "$450", "Nonstop"),
                          ("AA 200", "11:00→18:00", "$385", "1 stop")])
    lines = [f"Flights  {origin} → {dest}:"]
    for fl, sched, price, stops in flights:
        lines.append(f"  {fl:<8} {sched:<22} {price:<6}  [{stops}]")
    return "\n".join(lines)


def _mock_search_hotels(**kwargs) -> str:
    query = kwargs.get("query", "")
    city  = _extract_city(query)
    m     = re.search(r'(\d+)\s*night', query.lower())
    nights = int(m.group(1)) if m else 3
    hotels = {
        "Paris":  [("Le Marais Boutique", "⭐⭐⭐⭐",  f"€{185*nights}", "0.4 km to Louvre"),
                   ("Hotel des Arts",     "⭐⭐⭐",    f"€{95*nights}",  "Montmartre, near Sacré-Cœur"),
                   ("Plaza Athénée",      "⭐⭐⭐⭐⭐", f"€{520*nights}", "Avenue Montaigne, luxury")],
        "London": [("The Hoxton",         "⭐⭐⭐⭐",  f"£{150*nights}", "Shoreditch, near City"),
                   ("Premier Inn",        "⭐⭐⭐",    f"£{75*nights}",  "Westminster, transport links"),
                   ("The Savoy",          "⭐⭐⭐⭐⭐", f"£{450*nights}", "Strand, Thames views")],
    }
    props = hotels.get(city, [
        ("City Center Hotel", "⭐⭐⭐⭐",  f"${120*nights}", "Central location"),
        ("Budget Inn",        "⭐⭐⭐",    f"${65*nights}",  "Near transport links"),
        ("Grand Palace",      "⭐⭐⭐⭐⭐", f"${280*nights}", "5-star, city views"),
    ])
    lines = [f"Hotels in {city}  ({nights} nights):"]
    for name, stars, price, note in props:
        lines.append(f"  {name:<26} {stars}  {price:<10}  [{note}]")
    return "\n".join(lines)


def _mock_get_travel_advisories(**kwargs) -> str:
    return ("Travel Advisories (current):\n"
            "  🟢 France  — No advisory; safe for tourist travel\n"
            "  🟢 Japan   — No advisory; low crime, excellent infrastructure\n"
            "  🟡 Egypt   — Exercise caution; petty crime in tourist areas\n"
            "  🔴 Sudan   — Do not travel; active conflict\n"
            "  ℹ  Check ESTA/eVisa and vaccination requirements before booking")


def _mock_get_schedule(**kwargs) -> str:
    return ("Schedule — Tomorrow (Wednesday):\n"
            "  09:00  Engineering standup       [Google Meet, 30 min]\n"
            "  11:00  Product roadmap review    [Conf Room A, 90 min]\n"
            "  14:00  1:1 with Sarah            [Zoom, 30 min]\n"
            "  16:00  CLIENT — Acme Q3 review   [Teams, 60 min]\n"
            "  Free: 12:30–14:00, after 17:00")


def _mock_create_event(**kwargs) -> str:
    q = kwargs.get("query", "")
    for word in ["meeting", "call", "review", "sync", "standup", "interview"]:
        if word in q.lower():
            title = f"Team {word.title()}"
            break
    else:
        title = "New Event"
    return (f"✅ Event created: '{title}'\n"
            "  Date: Tomorrow 10:00–11:00\n"
            "  Invite sent to: team@company.com\n"
            "  Confirmed in Google Calendar")


def _mock_find_availability(**kwargs) -> str:
    return ("Next available slots:\n"
            "  ✓ Wednesday  12:30–14:00  (90 min free)\n"
            "  ✓ Thursday   09:00–11:00  (2 hrs free)\n"
            "  ✓ Friday     All day free\n"
            "  Earliest 30-min slot: Wednesday 12:30")


# ─────────────────────────────────────────────────────────────
# TOOL REGISTRATION — Single registration point; no agent code changes needed
# ─────────────────────────────────────────────────────────────

def _register_all_tools(registry: ToolRegistry) -> None:
    # ── Financial ─────────────────────────────────────────────────────────
    for name, desc, fn in [
        ("get_stock_price",      "Get real-time stock price and key metrics for a ticker",       _mock_get_stock_price),
        ("get_portfolio_summary","Retrieve portfolio holdings, total value, and day P&L",        _mock_get_portfolio_summary),
        ("get_market_news",      "Fetch latest market headlines and analyst commentary",          _mock_get_market_news),
    ]:
        registry.register(ToolDefinition(name=name, description=desc,
                                         agent_id="FinancialAgent",
                                         category="financial_query",
                                         parameters={}, mock_fn=fn))

    # ── Weather ────────────────────────────────────────────────────────────
    for name, desc, fn in [
        ("get_current_weather", "Get current weather conditions for a city",                     _mock_get_current_weather),
        ("get_forecast",        "Get 5-day weather forecast for a city",                         _mock_get_forecast),
        ("get_weather_alerts",  "Retrieve active severe weather warnings and storm alerts",       _mock_get_weather_alerts),
    ]:
        registry.register(ToolDefinition(name=name, description=desc,
                                         agent_id="WeatherAgent",
                                         category="weather_query",
                                         parameters={}, mock_fn=fn))

    # ── Travel ─────────────────────────────────────────────────────────────
    for name, desc, fn in [
        ("search_flights",       "Search available flights between two cities on a given date",   _mock_search_flights),
        ("search_hotels",        "Find and compare hotels in a destination city",                 _mock_search_hotels),
        ("get_travel_advisories","Get current government travel safety advisories by country",    _mock_get_travel_advisories),
    ]:
        registry.register(ToolDefinition(name=name, description=desc,
                                         agent_id="TravelAgent",
                                         category="travel_query",
                                         parameters={}, mock_fn=fn))

    # ── Calendar ───────────────────────────────────────────────────────────
    for name, desc, fn in [
        ("get_schedule",     "Retrieve the user's calendar events for a given day",              _mock_get_schedule),
        ("create_event",     "Create a new calendar event with title, time, and attendees",      _mock_create_event),
        ("find_availability","Find the next available free time slot of a given duration",       _mock_find_availability),
    ]:
        registry.register(ToolDefinition(name=name, description=desc,
                                         agent_id="CalendarAgent",
                                         category="calendar_query",
                                         parameters={}, mock_fn=fn))


# ─────────────────────────────────────────────────────────────
# DEMOS
# ─────────────────────────────────────────────────────────────

def _sep(label: str = "") -> None:
    if label:
        print(f"\n{'═' * 62}")
        print(f"  {label}")
        print(f"{'═' * 62}")
    else:
        print(f"\n  {'─' * 58}")


def demo_1_happy_path(orch: CentralOrchestrator) -> None:
    _sep("DEMO 1 — Happy Path: 7 queries across 4 agents")
    queries = [
        "What is the current stock price of Google?",
        "Is it going to rain in London tomorrow?",
        "Find me a flight from New York to Los Angeles next Friday",
        "Do I have any meetings tomorrow afternoon?",
        "What's the latest news on tech stocks?",
        "Book a hotel in Paris for 3 nights",
        "What's my current portfolio worth?",
    ]
    for q in queries:
        _sep()
        orch.handle(q)

    _sep("Demo 1 Summary")
    print(f"\n  {len(queries)} queries handled — each routed to exactly one specialist.")
    print("  No agent was exposed to tools outside its own domain.")
    print("  WeatherAgent never saw get_stock_price. FinancialAgent never saw search_flights.")


def demo_2_unknown_fallback(orch: CentralOrchestrator) -> None:
    _sep("DEMO 2 — Graceful Fallback for Unroutable Requests")
    unknowns = [
        "Tell me a joke about programmers",
        "What is the meaning of life?",
        "Translate 'hello world' to Spanish",
    ]
    for q in unknowns:
        _sep()
        orch.handle(q)
    print("\n  Key: UNKNOWN queries return a clear message — not a hallucinated answer.")
    print("  No agent is forced to misuse its tools on an out-of-scope request.")


def demo_3_registry_inspection(orch: CentralOrchestrator) -> None:
    _sep("DEMO 3 — Tool Registry (Dynamic Routing Context)")
    print("\n  Auto-generated routing context (what the LLM router sees):\n")
    print(orch.registry.routing_context())

    print("\n  Tool scoping — what each agent can see:\n")
    for agent_id, agent in orch.agents.items():
        print(f"  {agent_id:<18} → {list(agent._tools.keys())}")

    print("\n  To add a new agent: call registry.register() with new tool entries.")
    print("  The router's LLM prompt updates automatically — zero code changes.")


if __name__ == "__main__":
    _sep("TOOL ROUTING IN MULTI-AGENT CONTEXTS")
    mode = "LLM mode (Anthropic API)" if USE_LLM else "DEMO MODE — mock tools (set ANTHROPIC_API_KEY for real LLM)"
    print(f"\n  {mode}\n")

    orch = CentralOrchestrator()
    demo_1_happy_path(orch)
    demo_2_unknown_fallback(orch)
    demo_3_registry_inspection(orch)
