Create a new Agent Negotiation implementation for the following domain: $ARGUMENTS

Follow the Agent Negotiation pattern exactly:

**Step 1 — Define ResourceRequest, Offer, NegotiationOutcome dataclasses**
- `ResourceRequest`: agent_id, resource_id, start_hour (0–23), duration (hours), priority (1–4), flexibility (0–3)
- `Offer`: offer_id (uuid hex), from_agent, proposed_start, duration, reasoning, round_num, offer_type (INITIAL/COUNTER/FORCED/REJECT)
- `NegotiationOutcome`: resource_id, status (AGREED/PARTIAL/DEADLOCKED), schedule (dict[agent_id→(start,end)]), rounds_taken, transcript (list[dict])

**Step 2 — Define flexibility constants**
```python
FLEX_MAX_DEFER = {0: 0, 1: 2, 2: 6, 3: 20}  # max hours deferral per tier
FLEX_NAME      = {0: "RIGID", 1: "LOW", 2: "MEDIUM", 3: "HIGH"}
PRIORITY_NAME  = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}
```

**Step 3 — Build NegotiatingAgent base + minimum 4 domain specialists**
- `generate_counter(blocked: list[tuple[int,int]], round_num) → Optional[Offer]`
  - If `flexibility == 0`: return None (RIGID)
  - Scan `range(pref, pref + max_defer + 1)`, skip `pref` itself and conflicting slots
  - Return first valid candidate as Offer with reasoning
  - LLM path: `propose_counter` tool_use → `{proposed_start_hour, reasoning}`
- Specialists are subclasses with no overrides — all logic is in base + flexibility value
- Include at least one RIGID agent (flexibility=0) for the forced resolution demo

**Step 4 — Build ResourceManagerAgent**
- `__init__(agents, maintenance_windows=[])`:
  - Pre-populate `confirmed` with maintenance windows as `_maintenance_N` keys
- `negotiate() → NegotiationOutcome`:
  1. Sort agents: `-priority`, then `agent_id` (deterministic tie-breaking)
  2. For each agent in order:
     - If no conflicts with `confirmed`: GRANT, add to confirmed
     - Else: CONFLICT → negotiation loop (up to MAX_ROUNDS=5):
       a. `agent.generate_counter(all_blocked_dur, round_num)`
       b. If None → REJECT, break loop
       c. Validate against ALL confirmed (not just direct conflict)
       d. If valid → ACCEPT, confirm, break
       e. If still conflicts → append to `all_blocked_dur`, retry
     - If loop ends without resolution → `_force_slot()` → FORCED
  3. Strip `_maintenance_*` keys from final schedule
  4. status = AGREED / PARTIAL (forced used) / DEADLOCKED
- `_force_slot(req, confirmed)`: scan 0..23, ignore flexibility, return first open (start, end)
- `_overlaps(s1, d1, s2, d2) → bool`: `s1 < s2+d2 and s2 < s1+d1`

**Step 5 — Print helpers**
- `_print_header(agents, maintenance_windows)` — table of all requests
- `_print_event(ev)` — per-event output with symbols:
  - ✅ GRANTED / ACCEPTED, ⚡ CONFLICT, ↩ COUNTER (with reasoning on next line), ✗ REJECT, ⚠ FORCED, ☠ DEADLOCKED
- `_print_summary(schedule, status, rounds, forced)`:
  - Final schedule table
  - ASCII timeline: one row per agent, `█` per hour, `░` for maintenance windows

**Step 6 — Four demos**
- Demo 1: two agents, 1 high-priority + 1 low-priority, clean 1-round resolution
- Demo 2: three agents cascading in priority order, 2–3 total rounds
- Demo 3: two RIGID equal-priority agents → forced resolution → PARTIAL status
- Demo 4: maintenance window + multi-agent → agents work around pre-blocked window

**Transcript event format:**
```python
{"type": "GRANT",    "agent": ..., "start": h, "end": h, "round": 0}
{"type": "CONFLICT", "agent": ..., "preferred": h, "blocked_by": [...]}
{"type": "COUNTER",  "agent": ..., "round": n, "start": h, "end": h, "reasoning": ..., "valid": bool}
{"type": "ACCEPT",   "agent": ..., "start": h, "end": h}
{"type": "REJECT",   "agent": ..., "round": n, "reason": ...}
{"type": "FORCED",   "agent": ..., "start": h, "end": h}
{"type": "DEADLOCKED", "agent": ...}
```

**ASCII timeline format:**
```
  Timeline (each █ = 1 hour):
    012345678901234567890123
    AgentName           ██████              
    OtherAgent                ████          
    [maintenance]           ░░              
```

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/negotiation_<domain>.py
