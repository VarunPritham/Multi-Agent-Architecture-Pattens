"""
Knowledge Sharing Pattern — Shared Epistemic Memory
----------------------------------------------------
Demonstrates:
  1. In-memory vector store with TF-IDF cosine similarity for semantic search
  2. Knowledge entries with provenance (agent_id, timestamp, confidence)
  3. Agents writing discoveries to shared memory
  4. Agents retrieving relevant knowledge via semantic search (not exact match)
  5. Trust mechanism — agents rate entries; low-rated entries lose retrieval weight
  6. Governance agent — audits, validates, and prunes stale/low-quality entries
  7. Collective intelligence metrics — show how the system improves over time
  8. LLM-enhanced mode (API key) for richer solution generation

Scenario: Customer support for ProWidget smart home devices
  Agent_Alpha discovers Error 503 fix → writes to KB
  Agent_Beta encounters similar issue → finds Alpha's solution via semantic search
  Agent_Gamma handles related but different error → adapts existing knowledge
  Agent_Delta synthesises multiple KB entries for a complex multi-symptom issue
  GovernanceAgent audits, rates, and prunes low-quality entries
"""

import math
import os
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import anthropic


# ─────────────────────────────────────────────────────────────
# 1. KNOWLEDGE ENTRY — The atom of shared memory
# ─────────────────────────────────────────────────────────────

@dataclass
class KnowledgeEntry:
    entry_id:           str
    problem_description: str
    solution_steps:     str
    agent_id:           str          # provenance — who discovered this
    confidence:         float        # 0.0–1.0 initial confidence
    tags:               list[str]    # domain tags for filtering
    created_at:         str = field(default_factory=lambda: datetime.now().isoformat())
    # Trust signals
    use_count:          int   = 0    # times retrieved and applied
    rating_sum:         float = 0.0  # sum of ratings (1–5 scale)
    rating_count:       int   = 0    # number of ratings
    is_deprecated:      bool  = False

    @property
    def average_rating(self) -> Optional[float]:
        return self.rating_sum / self.rating_count if self.rating_count > 0 else None

    @property
    def trust_score(self) -> float:
        """Combined score used for retrieval ranking (0.0–1.0)."""
        base = self.confidence
        if self.average_rating:
            # Blend initial confidence with peer ratings
            base = (base + (self.average_rating / 5.0)) / 2
        # Boost popular, frequently-used entries
        popularity_boost = min(0.1, self.use_count * 0.01)
        return min(1.0, base + popularity_boost)

    def __str__(self):
        rating_str = f"{self.average_rating:.1f}★" if self.average_rating else "unrated"
        return (f"[{self.entry_id[:8]}] {self.problem_description[:60]}\n"
                f"  By: {self.agent_id:20s} | conf={self.confidence:.0%} | "
                f"trust={self.trust_score:.0%} | uses={self.use_count} | {rating_str}")


# ─────────────────────────────────────────────────────────────
# 2. SHARED KNOWLEDGE BASE — In-memory vector store
#    Uses TF-IDF cosine similarity for semantic retrieval.
#    No external dependencies — pure Python + math.
# ─────────────────────────────────────────────────────────────

class SharedKnowledgeBase:
    """
    Simulates a vector database with semantic search.
    In production: replace _similarity() with embeddings from
    OpenAI, Cohere, or a local model — the interface stays identical.
    """

    DEPRECATION_THRESHOLD = 1.5   # average rating below this → candidate for deprecation
    MIN_RATINGS_FOR_ACTION = 2    # need at least N ratings before deprecating

    def __init__(self):
        self._entries:  list[KnowledgeEntry] = []
        self._stats = {"writes": 0, "reads": 0, "cache_hits": 0}

    # ── Write ────────────────────────────────────────────────

    def add_entry(self, agent_id: str, problem_description: str,
                  solution_steps: str, confidence: float = 0.8,
                  tags: list[str] = None) -> KnowledgeEntry:
        entry = KnowledgeEntry(
            entry_id            = str(uuid.uuid4()),
            problem_description = problem_description,
            solution_steps      = solution_steps,
            agent_id            = agent_id,
            confidence          = confidence,
            tags                = tags or [],
        )
        self._entries.append(entry)
        self._stats["writes"] += 1
        print(f"  [KB] ✍  Written by {agent_id}: '{problem_description[:55]}...'")
        return entry

    # ── Read (semantic search) ────────────────────────────────

    def semantic_search(self, query: str, top_k: int = 3,
                        min_similarity: float = 0.1,
                        tags: list[str] = None) -> list[tuple[KnowledgeEntry, float]]:
        """
        Returns top_k entries sorted by (similarity × trust_score).
        Filters out deprecated entries and optionally by tag.
        """
        self._stats["reads"] += 1
        active = [e for e in self._entries if not e.is_deprecated]
        if tags:
            active = [e for e in active if any(t in e.tags for t in tags)]

        scored = []
        for entry in active:
            sim = self._similarity(query, entry.problem_description + " " + entry.solution_steps)
            combined = sim * entry.trust_score
            if sim >= min_similarity:
                scored.append((entry, combined))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = scored[:top_k]

        if results:
            self._stats["cache_hits"] += 1
            for entry, _ in results:
                entry.use_count += 1

        return results

    # ── Trust mechanism ──────────────────────────────────────

    def rate_entry(self, entry_id: str, rating: float, rater_id: str):
        """Agents rate each other's entries (1–5 scale)."""
        entry = self._find(entry_id)
        if entry:
            entry.rating_sum   += rating
            entry.rating_count += 1
            print(f"  [KB] ★  {rater_id} rated [{entry_id[:8]}] → {rating:.0f}/5 "
                  f"(avg now {entry.average_rating:.1f})")

    # ── Governance ───────────────────────────────────────────

    def deprecate_entry(self, entry_id: str, reason: str, governor_id: str):
        entry = self._find(entry_id)
        if entry:
            entry.is_deprecated = True
            print(f"  [KB] ⛔ {governor_id} deprecated [{entry_id[:8]}]: {reason}")

    def get_deprecation_candidates(self) -> list[KnowledgeEntry]:
        return [
            e for e in self._entries
            if not e.is_deprecated
            and e.rating_count >= self.MIN_RATINGS_FOR_ACTION
            and e.average_rating < self.DEPRECATION_THRESHOLD
        ]

    # ── Stats ────────────────────────────────────────────────

    def stats(self) -> dict:
        active = [e for e in self._entries if not e.is_deprecated]
        agents = {e.agent_id for e in self._entries}
        return {
            "total_entries":      len(self._entries),
            "active_entries":     len(active),
            "deprecated_entries": len(self._entries) - len(active),
            "contributing_agents": len(agents),
            "total_writes":       self._stats["writes"],
            "total_reads":        self._stats["reads"],
            "cache_hits":         self._stats["cache_hits"],
            "hit_rate":           (f"{self._stats['cache_hits']/self._stats['reads']:.0%}"
                                   if self._stats["reads"] else "N/A"),
        }

    def print_all(self):
        print(f"\n  {'─'*58}")
        print(f"  KNOWLEDGE BASE ({len(self._entries)} entries)")
        print(f"  {'─'*58}")
        for entry in self._entries:
            status = "⛔ DEPRECATED" if entry.is_deprecated else "✓ ACTIVE"
            print(f"  {status}  {entry}")
        print(f"  {'─'*58}")

    # ── Internals ────────────────────────────────────────────

    def _find(self, entry_id: str) -> Optional[KnowledgeEntry]:
        return next((e for e in self._entries if e.entry_id == entry_id), None)

    def _similarity(self, text1: str, text2: str) -> float:
        """
        TF-IDF cosine similarity.
        In production: replace with actual embedding vectors.
        """
        def tokenise(text: str) -> list[str]:
            return re.findall(r'\b[a-z]{2,}\b', text.lower())

        def tf(tokens: list[str]) -> dict[str, float]:
            counts = Counter(tokens)
            total  = len(tokens) or 1
            return {w: c / total for w, c in counts.items()}

        t1, t2   = tokenise(text1), tokenise(text2)
        tf1, tf2 = tf(t1), tf(t2)
        vocab    = set(tf1) | set(tf2)

        # IDF boost for rare words (simple approximation)
        idf = {w: math.log(2 / (1 + sum([w in tf1, w in tf2]))) + 1 for w in vocab}

        v1 = [tf1.get(w, 0) * idf[w] for w in vocab]
        v2 = [tf2.get(w, 0) * idf[w] for w in vocab]

        dot     = sum(a * b for a, b in zip(v1, v2))
        mag1    = math.sqrt(sum(a * a for a in v1)) or 1
        mag2    = math.sqrt(sum(b * b for b in v2)) or 1
        return dot / (mag1 * mag2)


# ─────────────────────────────────────────────────────────────
# 3. SUPPORT AGENTS — Discover and share knowledge
# ─────────────────────────────────────────────────────────────

USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))
client  = anthropic.Anthropic() if USE_LLM else None

MOCK_SOLUTIONS = {
    "Error 503 ProWidget X": (
        "1. Ask user to open device settings. "
        "2. Navigate to Storage → Clear Cache. "
        "3. Restart the device. "
        "4. Reconnect to WiFi. "
        "Error 503 is consistently caused by a corrupt local cache after firmware updates."
    ),
    "ProWidget Y connection drop": (
        "1. Check WiFi channel — switch router to 2.4GHz band. "
        "2. Reduce distance between device and router. "
        "3. Update ProWidget Y firmware via companion app. "
        "4. Factory reset if issue persists (hold power 10s)."
    ),
    "ProWidget X authentication failure": (
        "1. Log out of the ProWidget companion app. "
        "2. Revoke device access in account security settings. "
        "3. Re-pair the device from scratch. "
        "Root cause: OAuth token expiry after 90 days — known issue in firmware v2.1."
    ),
    "ProWidget Z overheating": (
        "1. Check that device is not enclosed in a cabinet. "
        "2. Ensure firmware is v3.2+ which has thermal throttling fix. "
        "3. If temperature exceeds 70°C, issue RMA. "
        "Overheating in v3.0-v3.1 firmware is a known defect."
    ),
}


class SupportAgent:
    """A customer support agent that handles issues and shares/retrieves knowledge."""

    def __init__(self, agent_id: str, kb: SharedKnowledgeBase):
        self.agent_id = agent_id
        self.kb       = kb

    def handle_issue(self, customer_query: str,
                     inject_solution_key: str = None) -> str:
        print(f"\n  [{self.agent_id}] Handling: '{customer_query[:60]}'")

        # Step 1: Search shared KB first
        results = self.kb.semantic_search(customer_query, top_k=2, min_similarity=0.15)

        if results:
            best_entry, score = results[0]
            print(f"  [{self.agent_id}] KB HIT (score={score:.2f}) — "
                  f"using solution from {best_entry.agent_id}")
            solution = best_entry.solution_steps
            # Rate the entry after using it
            quality = 4.5 if score > 0.3 else 3.5
            self.kb.rate_entry(best_entry.entry_id, quality, self.agent_id)
            return solution

        # Step 2: No KB hit — discover solution independently
        print(f"  [{self.agent_id}] No KB hit — discovering solution...")
        solution = self._discover_solution(customer_query, inject_solution_key)

        # Step 3: Write new knowledge to KB (confidence proportional to certainty)
        self.kb.add_entry(
            agent_id            = self.agent_id,
            problem_description = customer_query,
            solution_steps      = solution,
            confidence          = 0.82,
            tags                = self._extract_tags(customer_query),
        )
        return solution

    def _discover_solution(self, query: str, mock_key: str = None) -> str:
        if not USE_LLM:
            # Use mock solution keyed by topic
            if mock_key and mock_key in MOCK_SOLUTIONS:
                return MOCK_SOLUTIONS[mock_key]
            # Best-effort mock match
            for key, sol in MOCK_SOLUTIONS.items():
                if any(word in query.lower() for word in key.lower().split()):
                    return sol
            return f"[{self.agent_id}] Investigated issue. Applied standard reset procedure. Monitoring."

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": (
                f"You are a customer support specialist for ProWidget smart devices. "
                f"Provide a numbered, step-by-step solution for this issue:\n\n{query}\n\n"
                f"Include the root cause if known. Be concise (4–6 steps)."
            )}]
        )
        return response.content[0].text

    @staticmethod
    def _extract_tags(query: str) -> list[str]:
        tags = []
        q = query.lower()
        if "error" in q or "503" in q or "504" in q: tags.append("error_code")
        if "connect" in q or "wifi" in q:            tags.append("connectivity")
        if "update" in q or "firmware" in q:         tags.append("firmware")
        if "prowidget x" in q:                       tags.append("prowidget_x")
        if "prowidget y" in q:                       tags.append("prowidget_y")
        if "prowidget z" in q:                       tags.append("prowidget_z")
        return tags


# ─────────────────────────────────────────────────────────────
# 4. GOVERNANCE AGENT — Audits, validates, prunes the KB
# ─────────────────────────────────────────────────────────────

class GovernanceAgent:
    """
    Periodically reviews the knowledge base for quality.
    Deprecates low-rated or stale entries.
    Flags conflicting solutions for human review.
    """

    def __init__(self, kb: SharedKnowledgeBase):
        self.agent_id = "GovernanceAgent"
        self.kb       = kb

    def run_audit(self):
        print(f"\n  [{self.agent_id}] Running knowledge base audit...")

        # Identify deprecation candidates
        candidates = self.kb.get_deprecation_candidates()
        if candidates:
            for entry in candidates:
                self.kb.deprecate_entry(
                    entry.entry_id,
                    reason    = f"Low avg rating ({entry.average_rating:.1f}/5) after {entry.rating_count} reviews",
                    governor_id = self.agent_id
                )
        else:
            print(f"  [{self.agent_id}] No entries flagged for deprecation.")

        # Check for duplicate/conflicting entries
        self._check_duplicates()

        print(f"  [{self.agent_id}] Audit complete.")

    def _check_duplicates(self):
        """Flag entries with very high similarity to each other."""
        entries = [e for e in self.kb._entries if not e.is_deprecated]
        flagged = []
        for i, e1 in enumerate(entries):
            for e2 in entries[i+1:]:
                sim = self.kb._similarity(e1.problem_description, e2.problem_description)
                if sim > 0.75:
                    flagged.append((e1, e2, sim))
        if flagged:
            print(f"  [{self.agent_id}] ⚠  {len(flagged)} near-duplicate pair(s) flagged for review:")
            for e1, e2, sim in flagged:
                print(f"    [{e1.entry_id[:8]}] ↔ [{e2.entry_id[:8]}] similarity={sim:.2f}")


# ─────────────────────────────────────────────────────────────
# 5. DEMO — Shows collective intelligence building over time
# ─────────────────────────────────────────────────────────────

def print_stats(kb: SharedKnowledgeBase):
    stats = kb.stats()
    print(f"\n{'='*60}")
    print(f"  KNOWLEDGE BASE STATISTICS")
    print(f"{'='*60}")
    for k, v in stats.items():
        print(f"  {k:28s} {v}")


if __name__ == "__main__":
    if not USE_LLM:
        print("[DEMO MODE] Using mock solutions (set ANTHROPIC_API_KEY for real LLM)\n")

    # Shared KB — accessible to all agents
    kb = SharedKnowledgeBase()

    # Initialise agents
    alpha    = SupportAgent("Agent_Alpha",   kb)
    beta     = SupportAgent("Agent_Beta",    kb)
    gamma    = SupportAgent("Agent_Gamma",   kb)
    delta    = SupportAgent("Agent_Delta",   kb)
    governor = GovernanceAgent(kb)

    print(f"{'='*60}")
    print("  PHASE 1 — Agents discover and share knowledge")
    print(f"{'='*60}")

    # Alpha discovers solution to Error 503 — writes to KB
    s1 = alpha.handle_issue(
        "Customer reports Error 503 on ProWidget X. Device shows red light, "
        "won't connect to app after recent firmware update.",
        inject_solution_key="Error 503 ProWidget X"
    )

    # Beta encounters same class of problem — gets KB hit
    s2 = beta.handle_issue(
        "User getting Error 503 on ProWidget X. Tried restarting router, "
        "still showing error. Happened after automatic update last night."
    )

    # Gamma handles ProWidget Y connectivity issue — new territory, writes KB
    s3 = gamma.handle_issue(
        "ProWidget Y keeps dropping WiFi connection every few hours. "
        "Customer says it's been happening since last week.",
        inject_solution_key="ProWidget Y connection drop"
    )

    print(f"\n{'='*60}")
    print("  PHASE 2 — Agents build on existing knowledge")
    print(f"{'='*60}")

    # Alpha encounters auth failure — different problem, writes new entry
    s4 = alpha.handle_issue(
        "ProWidget X shows authentication failure. App says device is "
        "not authorised. Customer hasn't changed passwords.",
        inject_solution_key="ProWidget X authentication failure"
    )

    # Delta handles complex multi-symptom issue — retrieves and synthesises
    s5 = delta.handle_issue(
        "ProWidget X won't connect, showing error codes, app keeps "
        "logging out automatically. Multiple issues at once."
    )

    # Gamma handles overheating — new knowledge
    s6 = gamma.handle_issue(
        "ProWidget Z device getting very hot. Customer says it's warm to "
        "touch and shutting down intermittently.",
        inject_solution_key="ProWidget Z overheating"
    )

    # Beta finds ProWidget Y issue — should hit Gamma's KB entry
    s7 = beta.handle_issue(
        "ProWidget Y disconnects from network every few hours. "
        "Customer is frustrated, this has been happening for a week."
    )

    print(f"\n{'='*60}")
    print("  PHASE 3 — Trust signals + Governance")
    print(f"{'='*60}")

    # Inject a low-quality entry to demonstrate governance
    bad_entry = kb.add_entry(
        agent_id            = "Agent_Rogue",
        problem_description = "ProWidget X any error just reset factory settings always",
        solution_steps      = "Factory reset. Always works. Don't bother troubleshooting.",
        confidence          = 0.3,
        tags                = ["prowidget_x"],
    )

    # Multiple agents rate the bad entry poorly
    kb.rate_entry(bad_entry.entry_id, 1.0, "Agent_Alpha")
    kb.rate_entry(bad_entry.entry_id, 1.5, "Agent_Beta")

    # Rate a good entry highly
    entries = [e for e in kb._entries if e.agent_id == "Agent_Alpha" and not e.is_deprecated]
    if entries:
        kb.rate_entry(entries[0].entry_id, 5.0, "Agent_Gamma")
        kb.rate_entry(entries[0].entry_id, 4.5, "Agent_Delta")

    # Governance agent audits and prunes
    governor.run_audit()

    # Final state
    kb.print_all()
    print_stats(kb)

    print(f"\n{'='*60}")
    print("  COLLECTIVE INTELLIGENCE OUTCOME")
    print(f"{'='*60}")
    stats = kb.stats()
    hits  = int(stats["cache_hits"]) if isinstance(stats["cache_hits"], int) else 0
    reads = int(stats["total_reads"])
    print(f"  Of {reads} support queries, {hits} were resolved using"
          f" shared KB knowledge — zero re-investigation needed.")
    print(f"  {stats['contributing_agents']} agents contributed to a pool of"
          f" {stats['active_entries']} active solutions.")
    print(f"  1 low-quality entry deprecated by GovernanceAgent — KB integrity maintained.")
