"""
Supervision Tree with Guarded Capabilities
------------------------------------------
Demonstrates:
  1. Hierarchical tree — Root → Branch Supervisors → Worker Agents
  2. Capability guarding — each agent spawned with only the tools it needs
  3. Policy violation detection — agent blocked instantly when using unlisted tool
  4. ONE_FOR_ONE restart — only the failed child restarts, siblings unaffected
  5. ONE_FOR_ALL restart — when shared state is corrupted, restart entire branch
  6. ESCALATE — supervisor crashes itself when it cannot recover a child
  7. Backoff logic — stop restarting an agent after N crashes in T seconds
  8. Blast radius containment — Research branch crash never touches Processing branch
  9. Incident log — every crash, restart, policy violation recorded centrally

Tree structure:
  RootSupervisor  (strategy: ESCALATE — unrecoverable failures bubble to root)
  ├── ResearchSupervisor  (strategy: ONE_FOR_ONE — isolate individual scraper crashes)
  │   ├── ScraperAgent-1  [tools: web_scrape, web_search]
  │   ├── ScraperAgent-2  [tools: web_scrape, web_search]
  │   └── ScraperAgent-3  [tools: web_scrape, web_search]
  └── ProcessingSupervisor  (strategy: ONE_FOR_ALL — shared state requires joint restart)
      ├── SummarizerAgent  [tools: summarize]
      └── StorageAgent     [tools: store_data]

Failure scenarios injected in this demo:
  - ScraperAgent-2: hits CAPTCHA → crash → ONE_FOR_ONE restart
  - ScraperAgent-1: attempts billing_api (not in tools) → PolicyViolation → logged + restart
  - ScraperAgent-3: crash loop (crashes 4 times fast) → backoff engaged
  - Processing branch: runs cleanly throughout, proving blast-radius containment
"""

import time
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, Type


# ─────────────────────────────────────────────────────────────
# 1. TOOL REGISTRY — The full set of available tools in the system.
#    An agent only gets a *subset* of these at spawn time.
# ─────────────────────────────────────────────────────────────

def tool_web_scrape(url: str) -> str:
    return f"<html>Content from {url} — 3,200 words of research data</html>"

def tool_web_search(query: str) -> list:
    return [f"Result {i}: {query} — source {i}.com" for i in range(1, 4)]

def tool_summarize(content: str) -> str:
    words = len(content.split())
    return f"[Summary] Condensed {words} words → 3 key findings extracted."

def tool_store_data(key: str, value: str) -> bool:
    return True  # simulates DB write

def tool_send_email(to: str, body: str) -> bool:
    return True  # sensitive — should only go to comms agents

def tool_billing_api(action: str, amount: float) -> dict:
    return {"status": "charged", "amount": amount}  # highly sensitive

# Full tool registry — supervisors reference this to build child capability sets
ALL_TOOLS: dict[str, Callable] = {
    "web_scrape":  tool_web_scrape,
    "web_search":  tool_web_search,
    "summarize":   tool_summarize,
    "store_data":  tool_store_data,
    "send_email":  tool_send_email,     # sensitive
    "billing_api": tool_billing_api,    # highly sensitive
}


# ─────────────────────────────────────────────────────────────
# 2. STATUS, STRATEGY, EXCEPTIONS
# ─────────────────────────────────────────────────────────────

class AgentStatus(str, Enum):
    RUNNING           = "RUNNING"
    CRASHED           = "CRASHED"
    POLICY_VIOLATION  = "POLICY_VIOLATION"
    RESTARTING        = "RESTARTING"
    BACKOFF           = "BACKOFF"      # too many crashes — supervisor gave up
    STOPPED           = "STOPPED"


class Strategy(str, Enum):
    ONE_FOR_ONE = "ONE_FOR_ONE"   # restart only the failed child
    ONE_FOR_ALL = "ONE_FOR_ALL"   # restart all children (corrupted shared state)
    ESCALATE    = "ESCALATE"      # crash self → let parent handle


class PolicyViolationError(Exception):
    pass

class SupervisorFailureError(Exception):
    def __init__(self, supervisor_id: str, cause: Exception):
        self.supervisor_id = supervisor_id
        self.cause = cause
        super().__init__(f"Supervisor {supervisor_id} could not recover: {cause}")


# ─────────────────────────────────────────────────────────────
# 3. INCIDENT LOG — Central audit trail of all failures/restarts
# ─────────────────────────────────────────────────────────────

@dataclass
class Incident:
    timestamp: str
    agent_id:  str
    kind:      str    # "CRASH" | "POLICY_VIOLATION" | "RESTART" | "BACKOFF" | "ESCALATE"
    detail:    str


class IncidentLog:
    def __init__(self):
        self._log: list[Incident] = []
        self._lock = threading.Lock()

    def record(self, agent_id: str, kind: str, detail: str):
        entry = Incident(
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3],
            agent_id  = agent_id,
            kind      = kind,
            detail    = detail
        )
        with self._lock:
            self._log.append(entry)

        icon = {"CRASH": "💥", "POLICY_VIOLATION": "🚫", "RESTART": "♻️",
                "BACKOFF": "⛔", "ESCALATE": "🆘"}.get(kind, "📋")
        print(f"  {icon} [{entry.timestamp}] {kind:18s} {agent_id:25s} — {detail}")

    def all(self) -> list[Incident]:
        with self._lock:
            return list(self._log)


INCIDENT_LOG = IncidentLog()


# ─────────────────────────────────────────────────────────────
# 4. BASE AGENT — Every node in the tree extends this.
#    The capability guard lives here: use_tool() checks the whitelist.
# ─────────────────────────────────────────────────────────────

class BaseAgent:

    def __init__(self, agent_id: str, allowed_tools: dict[str, Callable]):
        self.agent_id      = agent_id
        self.allowed_tools = allowed_tools   # ← the capability guard
        self.status        = AgentStatus.RUNNING
        self.error:        Optional[Exception] = None
        self._crash_times: list[float] = []  # for backoff calculation

    def use_tool(self, tool_name: str, *args, **kwargs):
        """
        The capability gate. Agents can ONLY call tools in their allowed_tools dict.
        Anything else is a PolicyViolation — worse than a crash because it's intentional.
        """
        if tool_name not in self.allowed_tools:
            err = PolicyViolationError(
                f"'{tool_name}' not in allowed_tools {list(self.allowed_tools.keys())}"
            )
            self.status = AgentStatus.POLICY_VIOLATION
            self.error  = err
            raise err
        return self.allowed_tools[tool_name](*args, **kwargs)

    def run(self, *args, **kwargs):
        raise NotImplementedError

    def restart(self):
        self.status = AgentStatus.RESTARTING
        self.error  = None
        time.sleep(0.05)   # brief reset pause
        self.status = AgentStatus.RUNNING
        INCIDENT_LOG.record(self.agent_id, "RESTART", "Agent restarted with clean state")

    def mark_crashed(self, error: Exception):
        self.status = AgentStatus.CRASHED
        self.error  = error
        self._crash_times.append(time.time())

    def recent_crash_count(self, window_seconds: float = 10.0) -> int:
        cutoff = time.time() - window_seconds
        return sum(1 for t in self._crash_times if t > cutoff)


# ─────────────────────────────────────────────────────────────
# 5. SUPERVISOR AGENT — Manages child lifecycle.
#    Monitors health, applies recovery strategy, enforces backoff.
# ─────────────────────────────────────────────────────────────

class SupervisorAgent(BaseAgent):

    BACKOFF_CRASH_LIMIT  = 3      # max crashes before backoff
    BACKOFF_WINDOW_SECS  = 10.0   # window to count crashes in

    def __init__(self, agent_id: str, allowed_tools: dict,
                 strategy: Strategy = Strategy.ONE_FOR_ONE):
        super().__init__(agent_id, allowed_tools)
        self.strategy:  Strategy = strategy
        self.children:  list[BaseAgent] = []

    def spawn_child(self, agent_cls: Type[BaseAgent], child_id: str,
                    child_tool_names: list[str]) -> BaseAgent:
        """
        Capability guarding: child tools must be a SUBSET of supervisor's tools.
        The supervisor cannot grant a capability it doesn't have itself.
        """
        for name in child_tool_names:
            if name not in self.allowed_tools:
                raise PermissionError(
                    f"{self.agent_id} cannot grant '{name}' — "
                    f"it's not in its own allowed_tools"
                )
        child_tools = {name: self.allowed_tools[name] for name in child_tool_names}
        child = agent_cls(child_id, child_tools)
        self.children.append(child)
        print(f"  [+] {self.agent_id} spawned {child_id} "
              f"with tools: {child_tool_names}")
        return child

    def monitor_loop(self):
        """Single monitoring pass. Called repeatedly by the supervisor's run loop."""
        for child in self.children:
            if child.status in (AgentStatus.CRASHED, AgentStatus.POLICY_VIOLATION):
                self._handle_failure(child)

    def _handle_failure(self, failed: BaseAgent):
        kind = "CRASH" if failed.status == AgentStatus.CRASHED else "POLICY_VIOLATION"
        INCIDENT_LOG.record(failed.agent_id, kind, str(failed.error))

        # Backoff check — don't restart if crashing too frequently
        if failed.recent_crash_count(self.BACKOFF_WINDOW_SECS) >= self.BACKOFF_CRASH_LIMIT:
            failed.status = AgentStatus.BACKOFF
            INCIDENT_LOG.record(
                failed.agent_id, "BACKOFF",
                f"Crashed {self.BACKOFF_CRASH_LIMIT}+ times in "
                f"{self.BACKOFF_WINDOW_SECS}s — stopping restarts"
            )
            return

        # Apply recovery strategy
        if self.strategy == Strategy.ONE_FOR_ONE:
            failed.restart()

        elif self.strategy == Strategy.ONE_FOR_ALL:
            INCIDENT_LOG.record(
                self.agent_id, "RESTART",
                f"ONE_FOR_ALL triggered by {failed.agent_id} — restarting all children"
            )
            for child in self.children:
                child.restart()

        elif self.strategy == Strategy.ESCALATE:
            err = SupervisorFailureError(self.agent_id, failed.error)
            self.mark_crashed(err)
            raise err


# ─────────────────────────────────────────────────────────────
# 6. WORKER AGENTS — The actual task-doers.
#    They use tools, can fail; supervisors handle what happens next.
# ─────────────────────────────────────────────────────────────

class ScraperAgent(BaseAgent):
    """Scrapes a URL. Allowed tools: web_scrape, web_search only."""

    def run(self, url: str, inject_failure: str = None) -> Optional[str]:
        """
        inject_failure options:
          "captcha"  — simulates a blocking captcha error
          "policy"   — tries to call billing_api (not in tools) → PolicyViolation
          "loop"     — crashes every time (triggers backoff)
        """
        try:
            if inject_failure == "captcha":
                raise RuntimeError("CAPTCHA block — cannot proceed")
            if inject_failure == "policy":
                # Agent misbehaves — tries to access a tool outside its scope
                return self.use_tool("billing_api", "charge", 99.99)
            if inject_failure == "loop":
                raise RuntimeError("Persistent error — retrying won't help")

            # Normal execution
            content = self.use_tool("web_scrape", url)
            return content

        except PolicyViolationError:
            raise  # already set status — let supervisor handle
        except Exception as e:
            self.mark_crashed(e)
            raise


class SummarizerAgent(BaseAgent):
    """Summarizes scraped content. Allowed tools: summarize only."""

    def run(self, content: str) -> Optional[str]:
        try:
            return self.use_tool("summarize", content)
        except Exception as e:
            self.mark_crashed(e)
            raise


class StorageAgent(BaseAgent):
    """Stores results. Allowed tools: store_data only."""

    def run(self, key: str, value: str) -> bool:
        try:
            return self.use_tool("store_data", key, value)
        except Exception as e:
            self.mark_crashed(e)
            raise


# ─────────────────────────────────────────────────────────────
# 7. THE SUPERVISION TREE — Root builds and runs the whole system
# ─────────────────────────────────────────────────────────────

class RootSupervisor(SupervisorAgent):
    """
    The root of the tree. Has access to ALL tools so it can delegate
    any subset to child supervisors. Escalation stops here.
    """

    def __init__(self):
        super().__init__(
            agent_id     = "RootSupervisor",
            allowed_tools = ALL_TOOLS,
            strategy     = Strategy.ESCALATE  # unrecoverable → root logs and halts branch
        )

    def build_tree(self):
        print(f"\n{'='*60}")
        print(f"  [RootSupervisor] Building supervision tree...")
        print(f"{'='*60}\n")

        # ── Research Branch ───────────────────────────────────
        # ONE_FOR_ONE: if one scraper crashes, only restart that one
        research_sup = SupervisorAgent(
            agent_id      = "ResearchSupervisor",
            allowed_tools = {k: ALL_TOOLS[k] for k in ["web_scrape", "web_search"]},
            strategy      = Strategy.ONE_FOR_ONE
        )
        self.children.append(research_sup)

        # Each scraper only gets web_scrape + web_search — NOT billing, NOT email
        scraper1 = research_sup.spawn_child(ScraperAgent, "ScraperAgent-1",
                                            ["web_scrape", "web_search"])
        scraper2 = research_sup.spawn_child(ScraperAgent, "ScraperAgent-2",
                                            ["web_scrape", "web_search"])
        scraper3 = research_sup.spawn_child(ScraperAgent, "ScraperAgent-3",
                                            ["web_scrape", "web_search"])

        # ── Processing Branch ─────────────────────────────────
        # ONE_FOR_ALL: summarizer and storage share state — if one breaks, restart both
        processing_sup = SupervisorAgent(
            agent_id      = "ProcessingSupervisor",
            allowed_tools = {k: ALL_TOOLS[k] for k in ["summarize", "store_data"]},
            strategy      = Strategy.ONE_FOR_ALL
        )
        self.children.append(processing_sup)

        summarizer = processing_sup.spawn_child(SummarizerAgent, "SummarizerAgent",
                                                ["summarize"])
        storage    = processing_sup.spawn_child(StorageAgent,    "StorageAgent",
                                                ["store_data"])

        return research_sup, processing_sup, scraper1, scraper2, scraper3, summarizer, storage

    def run_pipeline(self):
        tree = self.build_tree()
        research_sup, processing_sup, s1, s2, s3, summarizer, storage = tree

        urls = [
            "https://research.ai/paper-1",
            "https://research.ai/paper-2",
            "https://research.ai/paper-3",
        ]

        print(f"\n{'─'*60}")
        print(f"  Phase 1: Research Branch — Scraping {len(urls)} URLs")
        print(f"{'─'*60}")

        results = {}

        # ── ScraperAgent-1: Policy violation attempt ──────────
        print(f"\n  Running {s1.agent_id}...")
        try:
            results["url1"] = s1.run(urls[0], inject_failure="policy")
        except (PolicyViolationError, RuntimeError):
            research_sup.monitor_loop()

        # ── ScraperAgent-2: CAPTCHA crash → ONE_FOR_ONE restart ──
        print(f"\n  Running {s2.agent_id}...")
        try:
            results["url2"] = s2.run(urls[1], inject_failure="captcha")
        except RuntimeError:
            research_sup.monitor_loop()
            # After restart, run again cleanly
            if s2.status == AgentStatus.RUNNING:
                print(f"  [{s2.agent_id}] Retrying after restart...")
                results["url2"] = s2.run(urls[1])  # clean run

        # ── ScraperAgent-3: Crash loop → backoff ─────────────
        print(f"\n  Running {s3.agent_id} (crash loop scenario)...")
        for attempt in range(5):
            try:
                results["url3"] = s3.run(urls[2], inject_failure="loop")
                break
            except RuntimeError:
                research_sup.monitor_loop()
                if s3.status == AgentStatus.BACKOFF:
                    print(f"  [{s3.agent_id}] Skipping — agent in backoff")
                    break

        # ── Research summary ─────────────────────────────────
        healthy_results = {k: v for k, v in results.items() if v}
        print(f"\n  Research branch complete: "
              f"{len(healthy_results)}/{len(urls)} URLs scraped successfully")

        print(f"\n{'─'*60}")
        print(f"  Phase 2: Processing Branch — Summarize & Store")
        print(f"{'─'*60}")

        # Processing branch runs cleanly — proving blast-radius containment
        for key, content in healthy_results.items():
            print(f"\n  Running {summarizer.agent_id} on {key}...")
            summary = summarizer.run(content)
            print(f"    → {summary}")

            print(f"  Running {storage.agent_id}...")
            stored = storage.run(key, summary)
            print(f"    → Stored: {stored}")

        processing_sup.monitor_loop()  # nothing to recover — branch ran cleanly


# ─────────────────────────────────────────────────────────────
# 8. DEMO
# ─────────────────────────────────────────────────────────────

def print_incident_summary():
    print(f"\n{'='*60}")
    print(f"  INCIDENT LOG SUMMARY")
    print(f"{'='*60}")
    incidents = INCIDENT_LOG.all()
    counts = {}
    for inc in incidents:
        counts[inc.kind] = counts.get(inc.kind, 0) + 1
    for kind, count in sorted(counts.items()):
        print(f"  {kind:20s} {count} event(s)")

    print(f"\n  Full log ({len(incidents)} entries):")
    for inc in incidents:
        print(f"    [{inc.timestamp}] {inc.kind:18s} {inc.agent_id:25s} — {inc.detail}")


if __name__ == "__main__":
    root = RootSupervisor()
    root.run_pipeline()
    print_incident_summary()

    # ── Verify capability isolation ──────────────────────────
    print(f"\n{'='*60}")
    print(f"  CAPABILITY GUARD VERIFICATION")
    print(f"{'='*60}")

    # Directly attempt to grant a child a tool the supervisor doesn't have
    research_sup = next(c for c in root.children if c.agent_id == "ResearchSupervisor")
    print(f"\n  Attempting to grant billing_api to a ScraperAgent...")
    try:
        research_sup.spawn_child(ScraperAgent, "RogueAgent", ["billing_api"])
    except PermissionError as e:
        print(f"  ✓ BLOCKED — {e}")

    print(f"\n  Attempting to grant store_data (ResearchSupervisor doesn't have it)...")
    try:
        research_sup.spawn_child(ScraperAgent, "RogueAgent2", ["store_data"])
    except PermissionError as e:
        print(f"  ✓ BLOCKED — {e}")
