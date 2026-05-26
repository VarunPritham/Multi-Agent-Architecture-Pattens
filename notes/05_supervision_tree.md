# Supervision Tree with Guarded Capabilities
## Fault Isolation + Principle of Least Privilege

---

## What Problem Does This Solve?

In production, agents call unstable external APIs, execute generated code, scrape hostile websites. Any of these can fail unpredictably. Without a supervision structure:

- One agent's unhandled exception crashes the entire orchestrator
- A compromised agent can call any tool in the system
- Recovery is manual — someone gets paged at 3am

The Supervision Tree solves fault containment and capability enforcement simultaneously: agents can fail freely (the supervisor handles recovery), and they're physically incapable of accessing tools outside their scope.

---

## Two Principles Working Together

### "Let It Crash" (from Erlang/Actor Model)
Don't write defensive code in every agent. Let the agent fail cleanly. Make the **supervisor** responsible for detecting the failure and deciding what to do. This separation keeps agent code simple and recovery logic centralised.

```
Without supervision:          With supervision:
─────────────────────         ─────────────────────
try:                          def run(self, url):
  result = scrape(url)            content = self.use_tool("web_scrape", url)
except CaptchaError:              return content     ← no try/except needed
  log_it()                        
  retry_maybe()             # Supervisor handles the crash
  ...
```

### Principle of Least Privilege
Each agent is spawned with exactly the tools it needs — nothing more. A `ScraperAgent` doing web research has zero ability to touch `billing_api`, not because of runtime checks in billing code, but because the capability simply doesn't exist in its tool dict.

---

## The Tree Structure

```
RootSupervisor  ← has ALL tools; never does domain work
├── ResearchSupervisor  [tools: web_scrape, web_search]  strategy: ONE_FOR_ONE
│   ├── ScraperAgent-1  [tools: web_scrape, web_search]
│   ├── ScraperAgent-2  [tools: web_scrape, web_search]
│   └── ScraperAgent-3  [tools: web_scrape, web_search]
└── ProcessingSupervisor  [tools: summarize, store_data]  strategy: ONE_FOR_ALL
    ├── SummarizerAgent  [tools: summarize]
    └── StorageAgent     [tools: store_data]
```

**Capability inheritance rule**: a supervisor can only grant tools it possesses itself. `ResearchSupervisor` has `[web_scrape, web_search]`, so it cannot spawn any child with `billing_api`, `store_data`, or `send_email`. The capability boundary propagates down the tree.

---

## The Three Recovery Strategies

### ONE_FOR_ONE — Independent failures
```
ScraperAgent-1: RUNNING   ScraperAgent-1: RUNNING
ScraperAgent-2: CRASHED → ScraperAgent-2: RESTARTING → RUNNING
ScraperAgent-3: RUNNING   ScraperAgent-3: RUNNING
```
Use when workers are stateless and independent. The most common strategy.

### ONE_FOR_ALL — Corrupted shared state
```
SummarizerAgent: RUNNING   SummarizerAgent: RESTARTING
StorageAgent:    CRASHED → StorageAgent:    RESTARTING
                           (both restarted together)
```
Use when workers share a memory buffer, database connection, or cached state. If one is corrupt, all could be.

### ESCALATE — Unrecoverable failure
```
ResearchSupervisor detects unrecoverable child
    → Supervisor crashes itself
        → RootSupervisor detects supervisor crash
            → Root decides: halt branch / alert human / switch to fallback
```
Use at the root level or when the supervisor itself can't determine how to recover.

---

## Backoff Logic — Preventing Crash Loops

Without backoff, a permanently broken agent would restart infinitely, burning compute:

```
Without backoff:                With backoff:
CRASH → RESTART                 CRASH → RESTART
CRASH → RESTART                 CRASH → RESTART
CRASH → RESTART                 CRASH → BACKOFF  ← stopped after N crashes in T seconds
CRASH → RESTART                 (agent stays in BACKOFF; escalated or manually resolved)
...forever
```

Implementation:
```python
def recent_crash_count(self, window_seconds=10.0) -> int:
    cutoff = time.time() - window_seconds
    return sum(1 for t in self._crash_times if t > cutoff)

# In supervisor:
if failed.recent_crash_count(window) >= BACKOFF_LIMIT:
    failed.status = AgentStatus.BACKOFF
    return  # stop restarting
```

---

## Policy Violation vs Crash

These are distinct incident types and should be treated differently:

| | Crash | Policy Violation |
|--|-------|-----------------|
| Cause | External failure (captcha, network) | Agent tried to use a tool outside its scope |
| Severity | Expected in production | Unexpected — potential security event |
| Recovery | Restart with same config | Restart + audit why it happened |
| Logging | `CRASH` | `POLICY_VIOLATION` (higher alert priority) |

```python
def use_tool(self, name, *args):
    if name not in self.allowed_tools:
        err = PolicyViolationError(f"'{name}' not in allowed_tools")
        self.status = AgentStatus.POLICY_VIOLATION
        self.error  = err
        raise err  # supervisor handles it differently from a CRASH
```

---

## The Incident Log

Every event in the supervision tree should be recorded centrally:

```
💥 CRASH              ScraperAgent-2     — CAPTCHA block
♻️ RESTART            ScraperAgent-2     — Agent restarted with clean state
🚫 POLICY_VIOLATION   ScraperAgent-1     — 'billing_api' not in allowed_tools
⛔ BACKOFF            ScraperAgent-3     — Crashed 3+ times in 10.0s
```

In production: ship these to your observability stack (Datadog, Grafana). Alert on POLICY_VIOLATION and BACKOFF — those require human review.

---

## Blast Radius Containment

The tree structure limits how far a failure can travel:

```
Research branch in chaos:         Processing branch:
ScraperAgent-2:  CRASHED           SummarizerAgent: RUNNING ✓
ScraperAgent-3:  BACKOFF           StorageAgent:    RUNNING ✓
ScraperAgent-1:  POLICY_VIOLATION
```

The `ProcessingSupervisor` has no knowledge of the Research branch's problems. Its children run cleanly throughout. This is the "blast radius" property: failure in one subtree cannot propagate to a sibling subtree without going through the root.

---

## Pros and Cons

### Pros
- **Self-healing**: automatic recovery without human intervention
- **Blast radius control**: crashes in risky branches don't touch safe branches
- **Least privilege**: capability guard is architectural, not just runtime checks
- **Observability**: structured incident log for every failure event

### Cons
- **Complexity**: developers must think in terms of trees and lifecycle management
- **Cross-branch communication**: agents in different branches can't share data directly — requires gateways through the root
- **Overhead**: lightweight for deep trees with many agents; overkill for simple 2-agent systems

---

## When to Use

✅ Use when:
- Agents use unstable external tools (web scraping, code execution, third-party APIs)
- You need automatic recovery without human intervention
- Security requires strict tool scoping (billing/admin cannot be touched by research agents)
- Running 5+ agents concurrently where one crash shouldn't halt others

❌ Avoid when:
- Simple, 2–3 agent sequential workflows (use Supervisor — simpler)
- Single-shot utilities where setup overhead > execution time
- All agents need access to the same tools (the capability guard doesn't add value)

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `supervision_tree.py` | Full research pipeline — two branches, three failure modes, backoff, capability guard verification, incident log |

---

## Real-World Equivalents

- **Erlang/OTP supervisors**: the original inspiration — Erlang systems run for years with zero downtime using exactly this pattern
- **Kubernetes pods/deployments**: pod crashes → deployment controller restarts it; resource limits = capability guard
- **Nuclear plant control rooms**: isolated control rooms (branches) each manage their domain; one room's failure doesn't propagate
- **Air traffic control**: each sector controller (supervisor) manages a geographic zone independently; problems in one zone don't cascade
