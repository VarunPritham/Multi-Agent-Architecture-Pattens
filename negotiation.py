"""
Agent Negotiation Pattern — Structured Resource Conflict Resolution
--------------------------------------------------------------------
Demonstrates:
  1. ResourceRequest — agents declare priority, duration, preferred slot, flexibility
  2. Conflict detection — mediator identifies overlapping time window requests
  3. Offer/counter-offer protocol — lower-priority agent proposes alternatives
  4. Flexibility constraint — each agent has a max deferral tolerance (RIGID → HIGH)
  5. Maintenance window support — pre-blocked slots act like confirmed reservations
  6. Forced resolution fallback — when negotiation fails, mediator imposes a slot
  7. Full audit transcript — every offer, rejection, and grant is logged
  8. Mock mode (no API key) + LLM mode (LLM-generated counter-offer reasoning)

Scenario: GPU server scheduling conflict resolution
  Agents request compute time on a shared GPU server.
  ResourceManagerAgent detects conflicts and runs the negotiation protocol.
  Higher-priority agents keep their preferred slot; lower-priority agents
  propose alternatives. RIGID agents cannot move; they get forced slots.
"""

import os
import uuid
from dataclasses import dataclass, field
from typing import Optional
import anthropic


USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))
client  = anthropic.Anthropic() if USE_LLM else None

# ── Flexibility tiers ────────────────────────────────────────
FLEX_MAX_DEFER = {0: 0, 1: 2, 2: 6, 3: 20}  # max hours of deferral per tier
FLEX_NAME      = {0: "RIGID", 1: "LOW", 2: "MEDIUM", 3: "HIGH"}
PRIORITY_NAME  = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}


# ─────────────────────────────────────────────────────────────
# 1. DATA STRUCTURES
# ─────────────────────────────────────────────────────────────

@dataclass
class ResourceRequest:
    agent_id:    str
    resource_id: str
    start_hour:  int     # preferred start (0–23)
    duration:    int     # hours
    priority:    int     # 1=LOW … 4=CRITICAL
    flexibility: int     # 0=RIGID … 3=HIGH


@dataclass
class Offer:
    offer_id:       str
    from_agent:     str
    proposed_start: int
    duration:       int
    reasoning:      str
    round_num:      int
    offer_type:     str  # INITIAL / COUNTER / FORCED / REJECT


@dataclass
class NegotiationOutcome:
    resource_id:  str
    status:       str    # AGREED / PARTIAL / DEADLOCKED
    schedule:     dict   # agent_id → (start_hour, end_hour)
    rounds_taken: int
    transcript:   list


# ─────────────────────────────────────────────────────────────
# 2. NEGOTIATING AGENTS — Each has preferences and flexibility
# ─────────────────────────────────────────────────────────────

class NegotiatingAgent:
    def __init__(self, agent_id: str, request: ResourceRequest):
        self.agent_id = agent_id
        self.request  = request

    @staticmethod
    def _overlaps(s1: int, d1: int, s2: int, d2: int) -> bool:
        return s1 < s2 + d2 and s2 < s1 + d1

    def generate_counter(
        self,
        blocked: list[tuple[int, int]],   # (start, duration) pairs to avoid
        round_num: int,
    ) -> Optional[Offer]:
        if self.request.flexibility == 0:
            return None    # RIGID — will not move under any circumstances

        if USE_LLM and client:
            return self._llm_generate_counter(blocked, round_num)
        return self._mock_generate_counter(blocked, round_num)

    def _mock_generate_counter(
        self, blocked: list[tuple[int, int]], round_num: int
    ) -> Optional[Offer]:
        max_defer = FLEX_MAX_DEFER[self.request.flexibility]
        pref, dur  = self.request.start_hour, self.request.duration

        # Scan forward from preferred start to find the first non-conflicting slot
        # within the flexibility window
        for candidate in range(pref, pref + max_defer + 1):
            if candidate == pref:
                continue   # original slot is blocked (why we're negotiating)
            if candidate + dur > 24:
                break
            if not any(self._overlaps(candidate, dur, bs, bd) for bs, bd in blocked):
                deferral = candidate - pref
                return Offer(
                    offer_id=uuid.uuid4().hex[:8],
                    from_agent=self.agent_id,
                    proposed_start=candidate,
                    duration=dur,
                    reasoning=(
                        f"Deferring +{deferral}h to {candidate:02d}:00 to avoid conflict "
                        f"[flex={FLEX_NAME[self.request.flexibility]}, max={max_defer}h]"
                    ),
                    round_num=round_num,
                    offer_type="COUNTER",
                )
        return None   # no valid slot within flexibility window

    def _llm_generate_counter(
        self, blocked: list[tuple[int, int]], round_num: int
    ) -> Optional[Offer]:
        blocked_desc = ", ".join(f"{s:02d}:00–{s+d:02d}:00" for s, d in blocked)
        schema = {
            "name": "propose_counter",
            "description": "Propose an alternative time slot for the job",
            "input_schema": {
                "type": "object",
                "properties": {
                    "proposed_start_hour": {
                        "type": "integer",
                        "description": "Alternative start hour (0–23)"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "One sentence explaining this choice"
                    }
                },
                "required": ["proposed_start_hour", "reasoning"]
            }
        }
        resp = client.messages.create(
            model="claude-opus-4-5", max_tokens=256,
            tools=[schema],
            tool_choice={"type": "tool", "name": "propose_counter"},
            messages=[{"role": "user", "content": (
                f"You are {self.agent_id}. Your GPU job: "
                f"preferred={self.request.start_hour:02d}:00, "
                f"duration={self.request.duration}h, "
                f"flexibility={FLEX_NAME[self.request.flexibility]} "
                f"(max defer {FLEX_MAX_DEFER[self.request.flexibility]}h).\n"
                f"Blocked time slots: {blocked_desc}.\n"
                f"Propose a valid alternative start hour within your flexibility window."
            )}]
        )
        for block in resp.content:
            if block.type == "tool_use":
                start = int(block.input["proposed_start_hour"])
                return Offer(
                    offer_id=uuid.uuid4().hex[:8],
                    from_agent=self.agent_id,
                    proposed_start=start,
                    duration=self.request.duration,
                    reasoning=block.input["reasoning"],
                    round_num=round_num,
                    offer_type="COUNTER",
                )
        return self._mock_generate_counter(blocked, round_num)


class AnalyticsAgent(NegotiatingAgent):
    """High-priority financial model. Short window, low flexibility."""
    pass


class TrainingAgent(NegotiatingAgent):
    """Low-priority routine retraining. Long window, high flexibility."""
    pass


class BackupAgent(NegotiatingAgent):
    """Medium-priority backup job. Medium flexibility."""
    pass


class MaintenanceAgent(NegotiatingAgent):
    """Medium-priority maintenance sweep. Moderate flexibility."""
    pass


class ReportingAgent(NegotiatingAgent):
    """Low-priority reporting job. Absolutely cannot move (RIGID)."""
    pass


class AuditAgent(NegotiatingAgent):
    """Low-priority compliance audit. Also RIGID."""
    pass


# ─────────────────────────────────────────────────────────────
# 3. RESOURCE MANAGER — Detects conflicts, runs protocol
# ─────────────────────────────────────────────────────────────

class ResourceManagerAgent:
    MAX_ROUNDS = 5

    def __init__(
        self,
        agents: list[NegotiatingAgent],
        maintenance_windows: Optional[list[tuple[int, int]]] = None,
    ):
        self.agents = {a.agent_id: a for a in agents}
        self.maintenance_windows: list[tuple[int, int]] = maintenance_windows or []

    @staticmethod
    def _overlaps(s1: int, d1: int, s2: int, d2: int) -> bool:
        return s1 < s2 + d2 and s2 < s1 + d1

    def negotiate(self) -> NegotiationOutcome:
        requests = [a.request for a in self.agents.values()]
        resource_id = requests[0].resource_id

        # Sort: highest priority first; tie-break alphabetically (deterministic)
        sorted_agents = sorted(
            self.agents.values(),
            key=lambda a: (-a.request.priority, a.agent_id),
        )

        # Pre-populate confirmed with maintenance windows (label: "maintenance")
        confirmed: dict[str, tuple[int, int]] = {}
        for i, (mw_start, mw_dur) in enumerate(self.maintenance_windows):
            confirmed[f"_maintenance_{i}"] = (mw_start, mw_start + mw_dur)

        transcript: list[dict] = []
        total_rounds = 0
        forced_agents: list[str] = []
        deadlocked_agents: list[str] = []

        self._print_header(sorted_agents, self.maintenance_windows)

        for agent in sorted_agents:
            req = agent.request

            # All currently blocked windows (start, duration)
            all_blocked_dur = [(s, e - s) for s, e in confirmed.values()]

            # Does this agent's preferred slot overlap anything?
            conflicts = [
                label for label, (s, e) in confirmed.items()
                if self._overlaps(req.start_hour, req.duration, s, e - s)
            ]

            if not conflicts:
                # No conflict — grant immediately (round 0)
                end = req.start_hour + req.duration
                confirmed[req.agent_id] = (req.start_hour, end)
                ev = dict(type="GRANT", agent=req.agent_id,
                          start=req.start_hour, end=end, round=0)
                transcript.append(ev)
                self._print_event(ev)

            else:
                # Conflict — initiate negotiation
                ev = dict(type="CONFLICT", agent=req.agent_id,
                          preferred=req.start_hour,
                          blocked_by=[c for c in conflicts if not c.startswith("_")])
                transcript.append(ev)
                self._print_event(ev)

                resolved = False
                for round_num in range(1, self.MAX_ROUNDS + 1):
                    total_rounds += 1

                    # Agent tries to find an alternative
                    offer = agent.generate_counter(all_blocked_dur, round_num)

                    if offer is None:
                        # Agent won't / can't move
                        ev = dict(type="REJECT", agent=req.agent_id, round=round_num,
                                  reason=f"flex={FLEX_NAME[req.flexibility]} — cannot defer")
                        transcript.append(ev)
                        self._print_event(ev)
                        break

                    offer_end = offer.proposed_start + offer.duration
                    still_conflicts = any(
                        self._overlaps(offer.proposed_start, offer.duration, s, e - s)
                        for s, e in confirmed.values()
                    )

                    ev = dict(type="COUNTER", agent=req.agent_id, round=round_num,
                              start=offer.proposed_start, end=offer_end,
                              reasoning=offer.reasoning, valid=not still_conflicts)
                    transcript.append(ev)
                    self._print_event(ev)

                    if not still_conflicts:
                        confirmed[req.agent_id] = (offer.proposed_start, offer_end)
                        ev = dict(type="ACCEPT", agent=req.agent_id,
                                  start=offer.proposed_start, end=offer_end)
                        transcript.append(ev)
                        self._print_event(ev)
                        resolved = True
                        break

                    # Counter still conflicts — add to blocked so agent avoids it next round
                    all_blocked_dur.append((offer.proposed_start, offer.duration))

                if not resolved:
                    forced = self._force_slot(req, confirmed)
                    if forced is not None:
                        confirmed[req.agent_id] = forced
                        ev = dict(type="FORCED", agent=req.agent_id,
                                  start=forced[0], end=forced[1])
                        transcript.append(ev)
                        self._print_event(ev)
                        forced_agents.append(req.agent_id)
                    else:
                        ev = dict(type="DEADLOCKED", agent=req.agent_id)
                        transcript.append(ev)
                        self._print_event(ev)
                        deadlocked_agents.append(req.agent_id)

        # Strip maintenance window keys from schedule
        schedule = {k: v for k, v in confirmed.items() if not k.startswith("_")}

        if deadlocked_agents:
            status = "DEADLOCKED"
        elif forced_agents:
            status = "PARTIAL"
        else:
            status = "AGREED"

        self._print_summary(schedule, status, total_rounds, forced_agents)

        return NegotiationOutcome(
            resource_id=resource_id,
            status=status,
            schedule=schedule,
            rounds_taken=total_rounds,
            transcript=transcript,
        )

    def _force_slot(
        self, req: ResourceRequest, confirmed: dict[str, tuple[int, int]]
    ) -> Optional[tuple[int, int]]:
        """Ignore flexibility — find ANY available slot on the day."""
        for start in range(0, 24 - req.duration + 1):
            end = start + req.duration
            if not any(
                self._overlaps(start, req.duration, s, e - s)
                for s, e in confirmed.values()
            ):
                return (start, end)
        return None

    # ── Printing helpers ──────────────────────────────────────

    def _print_header(
        self,
        agents: list[NegotiatingAgent],
        maint: list[tuple[int, int]],
    ) -> None:
        print(f"\n  ┌── Request Summary ─────────────────────────────────────────────")
        for a in agents:
            r = a.request
            print(
                f"  │  {a.agent_id:<20} priority={PRIORITY_NAME[r.priority]:<8} "
                f"flex={FLEX_NAME[r.flexibility]:<6}  "
                f"{r.start_hour:02d}:00–{r.start_hour+r.duration:02d}:00 ({r.duration}h)"
            )
        if maint:
            for ms, md in maint:
                print(f"  │  ⚙ MAINTENANCE WINDOW     {ms:02d}:00–{ms+md:02d}:00 (pre-blocked)")
        print(f"  └────────────────────────────────────────────────────────────────")

    def _print_event(self, ev: dict) -> None:
        t = ev["type"]
        if t == "GRANT":
            print(f"\n  ✅ GRANTED  {ev['agent']:<20} → {ev['start']:02d}:00–{ev['end']:02d}:00  (no conflict)")
        elif t == "CONFLICT":
            blocked_str = ", ".join(ev["blocked_by"]) or "maintenance window"
            print(f"\n  ⚡ CONFLICT  {ev['agent']:<20} wants {ev['preferred']:02d}:00 — blocked by {blocked_str}")
        elif t == "REJECT":
            print(f"  ✗ REJECT    {ev['agent']:<20} [round {ev['round']}] {ev['reason']}")
        elif t == "COUNTER":
            valid_tag = "✓ valid" if ev["valid"] else "✗ still conflicts"
            print(f"  ↩ COUNTER   {ev['agent']:<20} [round {ev['round']}] "
                  f"proposes {ev['start']:02d}:00–{ev['end']:02d}:00  [{valid_tag}]")
            print(f"             └─ {ev['reasoning']}")
        elif t == "ACCEPT":
            print(f"  ✅ ACCEPTED  {ev['agent']:<20} → {ev['start']:02d}:00–{ev['end']:02d}:00")
        elif t == "FORCED":
            print(f"  ⚠ FORCED    {ev['agent']:<20} → {ev['start']:02d}:00–{ev['end']:02d}:00  (mediator imposed)")
        elif t == "DEADLOCKED":
            print(f"  ☠ DEADLOCKED {ev['agent']:<19} — no slot found")

    def _print_summary(
        self,
        schedule: dict,
        status: str,
        rounds: int,
        forced: list[str],
    ) -> None:
        status_icon = {"AGREED": "✅", "PARTIAL": "⚠", "DEADLOCKED": "☠"}.get(status, "?")
        print(f"\n  {'─'*64}")
        print(f"  {status_icon} {status}  |  {rounds} negotiation round(s)")
        print(f"\n  Final schedule:")
        for agent_id, (start, end) in sorted(schedule.items()):
            forced_tag = "  ← forced" if agent_id in forced else ""
            bar = "█" * (end - start)
            print(f"  {'':2}{agent_id:<22} {start:02d}:00–{end:02d}:00  [{bar}]{forced_tag}")
        # ASCII timeline
        print(f"\n  Timeline (each █ = 1 hour):")
        print(f"  {'':2}{''.join(str(h % 10) for h in range(24))}")
        for agent_id, (start, end) in sorted(schedule.items()):
            bar = " " * start + "█" * (end - start) + " " * (24 - end)
            print(f"  {'':2}{agent_id[:18]:<18}  {bar}")
        for i, (ms, md) in enumerate(self.maintenance_windows):
            bar = " " * ms + "░" * md + " " * (24 - ms - md)
            print(f"  {'':2}{'[maintenance]':<18}  {bar}")


# ─────────────────────────────────────────────────────────────
# DEMOS
# ─────────────────────────────────────────────────────────────

def _sep(label: str = "") -> None:
    if label:
        print(f"\n{'═' * 66}")
        print(f"  {label}")
        print(f"{'═' * 66}")
    else:
        print(f"\n  {'─' * 62}")


def demo_1_two_party() -> NegotiationOutcome:
    _sep("DEMO 1 — Two-Party Conflict: Analytics vs Training")
    print("\n  Both agents request 02:00 on the GPU server.")
    print("  AnalyticsAgent is HIGH priority, LOW flex — keeps its slot.")
    print("  TrainingAgent is LOW priority, HIGH flex — must move.\n")

    agents = [
        AnalyticsAgent("AnalyticsAgent", ResourceRequest(
            "AnalyticsAgent", "GPU-01", start_hour=2, duration=2,
            priority=3, flexibility=1)),
        TrainingAgent("TrainingAgent", ResourceRequest(
            "TrainingAgent", "GPU-01", start_hour=2, duration=4,
            priority=1, flexibility=3)),
    ]
    return ResourceManagerAgent(agents).negotiate()


def demo_2_three_party_cascade() -> NegotiationOutcome:
    _sep("DEMO 2 — Three-Party Cascade: All want 02:00")
    print("\n  Three agents conflict on the same slot.")
    print("  Priority order: Analytics > Backup > Training.")
    print("  Each lower-priority agent defers after the slot above it is confirmed.\n")

    agents = [
        AnalyticsAgent("AnalyticsAgent", ResourceRequest(
            "AnalyticsAgent", "GPU-01", start_hour=2, duration=2,
            priority=3, flexibility=1)),
        BackupAgent("BackupAgent", ResourceRequest(
            "BackupAgent",    "GPU-01", start_hour=2, duration=3,
            priority=2, flexibility=2)),
        TrainingAgent("TrainingAgent", ResourceRequest(
            "TrainingAgent",  "GPU-01", start_hour=2, duration=4,
            priority=1, flexibility=3)),
    ]
    return ResourceManagerAgent(agents).negotiate()


def demo_3_rigid_forced() -> NegotiationOutcome:
    _sep("DEMO 3 — RIGID Agents: Forced Resolution Fallback")
    print("\n  Two equal-priority RIGID agents both want 08:00.")
    print("  Neither will negotiate. Alphabetically first is confirmed;")
    print("  the other gets the next available slot via forced resolution.\n")

    agents = [
        AuditAgent("AuditAgent", ResourceRequest(
            "AuditAgent",     "GPU-01", start_hour=8, duration=3,
            priority=1, flexibility=0)),
        ReportingAgent("ReportingAgent", ResourceRequest(
            "ReportingAgent", "GPU-01", start_hour=8, duration=3,
            priority=1, flexibility=0)),
    ]
    return ResourceManagerAgent(agents).negotiate()


def demo_4_maintenance_window() -> NegotiationOutcome:
    _sep("DEMO 4 — Maintenance Window + Multi-Agent Scheduling")
    print("\n  A pre-blocked maintenance window (08:00–10:00) acts like a confirmed")
    print("  reservation. Agents must navigate around both each other and the window.\n")

    agents = [
        AnalyticsAgent("AnalyticsAgent", ResourceRequest(
            "AnalyticsAgent",  "GPU-01", start_hour=2, duration=2,
            priority=3, flexibility=1)),
        MaintenanceAgent("MaintenanceAgent", ResourceRequest(
            "MaintenanceAgent","GPU-01", start_hour=4, duration=4,
            priority=2, flexibility=2)),
        TrainingAgent("TrainingAgent", ResourceRequest(
            "TrainingAgent",   "GPU-01", start_hour=4, duration=4,
            priority=1, flexibility=3)),
    ]
    return ResourceManagerAgent(
        agents,
        maintenance_windows=[(8, 2)],   # 08:00–10:00 off-limits
    ).negotiate()


if __name__ == "__main__":
    _sep("AGENT NEGOTIATION PATTERN — GPU Server Scheduling")
    mode = "LLM mode" if USE_LLM else "DEMO MODE — mock logic (set ANTHROPIC_API_KEY for real LLM)"
    print(f"\n  {mode}\n")

    r1 = demo_1_two_party()
    _sep()
    r2 = demo_2_three_party_cascade()
    _sep()
    r3 = demo_3_rigid_forced()
    _sep()
    r4 = demo_4_maintenance_window()

    _sep("Results Summary")
    for label, r in [("Demo 1", r1), ("Demo 2", r2), ("Demo 3", r3), ("Demo 4", r4)]:
        slots = "  ".join(
            f"{aid}→{s:02d}:00" for aid, (s, _) in sorted(r.schedule.items())
            if not aid.startswith("_")
        )
        print(f"  {label}  [{r.status:<10}]  {r.rounds_taken} round(s)  |  {slots}")
