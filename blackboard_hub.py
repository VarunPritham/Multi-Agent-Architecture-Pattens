"""
Blackboard Knowledge Hub — Collaborative Medical Diagnosis
----------------------------------------------------------
Demonstrates:
  1. Blackboard as a thread-safe, append-only fact repository
  2. Typed facts with confidence scores and agent provenance
  3. Eligibility conditions — agents self-select based on board state
  4. Controller-driven cycles: select → contribute → evaluate
  5. Convergence detection — when collective confidence is sufficient
  6. Full audit trail showing the emergent "chain of thought"
  7. Confidence thresholding — low-confidence facts don't trigger next agents
  8. Mock fallback when no API key is set

Problem flow (non-linear — the path emerges from facts posted):
  Raw symptoms posted
      ↓
  SymptomAnalysisAgent reads symptoms → posts initial hypotheses
      ↓
  DermatologyAgent sees "rash" → posts skin assessment
  VirologyAgent sees "viral" hypothesis → requests bloodwork
      ↓
  PathologyAgent sees bloodwork request → posts lab results
      ↓
  InfectiousDiseaseAgent sees sufficient evidence → posts diagnosis
      ↓
  Controller detects convergence → DiagnosisAgent synthesizes final answer
"""

import os
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import anthropic

# ─────────────────────────────────────────────────────────────
# 1. FACT TYPES — The typed vocabulary of the blackboard
#    Every fact must declare what kind of knowledge it is
# ─────────────────────────────────────────────────────────────

class FactType(str, Enum):
    SYMPTOM         = "symptom"          # raw patient observations
    HYPOTHESIS      = "hypothesis"       # proposed explanation
    TEST_REQUEST    = "test_request"     # request for additional data
    LAB_RESULT      = "lab_result"       # result of a requested test
    ASSESSMENT      = "assessment"       # specialist evaluation
    DIAGNOSIS       = "diagnosis"        # synthesized final conclusion


@dataclass
class Fact:
    fact_id:    str
    agent_id:   str
    fact_type:  FactType
    content:    str
    confidence: float           # 0.0 – 1.0
    timestamp:  str = field(default_factory=lambda: datetime.now().isoformat())
    metadata:   dict = field(default_factory=dict)

    def __str__(self):
        return (
            f"[{self.fact_type.upper():15s}] {self.agent_id:28s} "
            f"conf={self.confidence:.0%}  \"{self.content}\""
        )


# ─────────────────────────────────────────────────────────────
# 2. BLACKBOARD — The shared knowledge repository
#    Append-only. Thread-safe. Every write is permanent.
# ─────────────────────────────────────────────────────────────

class Blackboard:

    CONVERGENCE_THRESHOLD = 0.75   # minimum confidence to accept a diagnosis
    MIN_DIAGNOSIS_FACTS   = 3      # minimum supporting facts before diagnosing

    def __init__(self):
        self._facts: list[Fact] = []
        self._lock  = threading.Lock()
        self._counter = 0

    def post(self, agent_id: str, fact_type: FactType, content: str,
             confidence: float, metadata: dict = None) -> Fact:
        with self._lock:
            self._counter += 1
            fact = Fact(
                fact_id    = f"F{self._counter:03d}",
                agent_id   = agent_id,
                fact_type  = fact_type,
                content    = content,
                confidence = confidence,
                metadata   = metadata or {}
            )
            self._facts.append(fact)
        return fact

    def get_facts(self, fact_type: FactType = None,
                  min_confidence: float = 0.0) -> list[Fact]:
        with self._lock:
            facts = self._facts
            if fact_type:
                facts = [f for f in facts if f.fact_type == fact_type]
            return [f for f in facts if f.confidence >= min_confidence]

    def contains_keyword(self, keyword: str, fact_types: list[FactType] = None,
                         min_confidence: float = 0.5) -> bool:
        """Check if any fact contains a keyword — used by agents for eligibility."""
        facts = self.get_facts(min_confidence=min_confidence)
        if fact_types:
            facts = [f for f in facts if f.fact_type in fact_types]
        return any(keyword.lower() in f.content.lower() for f in facts)

    def has_fact_type(self, fact_type: FactType) -> bool:
        return len(self.get_facts(fact_type=fact_type)) > 0

    def check_convergence(self) -> bool:
        """Convergence: a high-confidence diagnosis exists with enough supporting facts."""
        diagnoses = self.get_facts(FactType.DIAGNOSIS, min_confidence=self.CONVERGENCE_THRESHOLD)
        supporting = (
            self.get_facts(FactType.HYPOTHESIS,  min_confidence=0.6) +
            self.get_facts(FactType.ASSESSMENT,  min_confidence=0.6) +
            self.get_facts(FactType.LAB_RESULT,  min_confidence=0.6)
        )
        return len(diagnoses) >= 1 and len(supporting) >= self.MIN_DIAGNOSIS_FACTS

    def all_facts(self) -> list[Fact]:
        with self._lock:
            return list(self._facts)


# ─────────────────────────────────────────────────────────────
# 3. KNOWLEDGE SOURCES (AGENTS)
#    Each has: eligibility_check() → should I act right now?
#              contribute()        → what do I add to the board?
#    Agents never call each other. Only read/write the board.
# ─────────────────────────────────────────────────────────────

USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))
client  = anthropic.Anthropic() if USE_LLM else None

MOCK_CONTRIBUTIONS = {
    "SymptomAnalysisAgent": [
        ("High fever (39.5°C) and widespread maculopapular rash — consistent with systemic viral or bacterial infection", 0.85, FactType.HYPOTHESIS),
        ("Symptom onset 3 days ago, no recent travel, no known contacts with infectious disease", 0.90, FactType.ASSESSMENT),
    ],
    "DermatologyAgent": [
        ("Rash morphology (maculopapular, centrifugal spread) strongly suggests viral exanthem — measles, rubella, or roseola most likely", 0.80, FactType.ASSESSMENT),
        ("No vesicular lesions, no target lesions — bacterial causes less likely", 0.75, FactType.HYPOTHESIS),
    ],
    "VirologyAgent": [
        ("Viral exanthem pattern with fever onset 2-3 days prior to rash — classic prodrome for measles or rubella", 0.82, FactType.HYPOTHESIS),
        ("Requesting CBC with differential, CRP, and IgM serology for measles/rubella confirmation", 0.95, FactType.TEST_REQUEST),
    ],
    "PathologyAgent": [
        ("CBC: WBC 3.2 (leukopenia), Lymphocytes 18% (lymphopenia) — consistent with viral infection", 0.88, FactType.LAB_RESULT),
        ("CRP: 45 mg/L (moderately elevated), IgM measles: positive (titer 1:320)", 0.95, FactType.LAB_RESULT),
    ],
    "InfectiousDiseaseAgent": [
        ("IgM-positive measles with classic prodrome, leukopenia, and maculopapular exanthem — diagnosis confirmed", 0.92, FactType.DIAGNOSIS),
        ("Recommend isolation, supportive care (hydration, antipyretics), Vitamin A supplementation per WHO protocol", 0.95, FactType.ASSESSMENT),
    ],
}


class BaseKnowledgeSource:

    def __init__(self, agent_id: str, board: Blackboard):
        self.agent_id = agent_id
        self.board    = board
        self._done    = False   # prevents an agent from contributing twice

    def is_eligible(self) -> bool:
        raise NotImplementedError

    def contribute(self):
        raise NotImplementedError

    def _llm_contribute(self, prompt: str) -> list[tuple]:
        """Ask the LLM for a list of (content, confidence, fact_type) contributions."""
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=[{
                "name": "post_facts",
                "description": "Post facts/hypotheses to the medical blackboard",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "contributions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content":     {"type": "string"},
                                    "confidence":  {"type": "number", "minimum": 0, "maximum": 1},
                                    "fact_type":   {"type": "string",
                                                    "enum": ["symptom", "hypothesis", "test_request",
                                                             "lab_result", "assessment", "diagnosis"]}
                                },
                                "required": ["content", "confidence", "fact_type"]
                            }
                        }
                    },
                    "required": ["contributions"]
                }
            }],
            tool_choice={"type": "tool", "name": "post_facts"},
            messages=[{"role": "user", "content": prompt}]
        )
        raw = next(b for b in response.content if b.type == "tool_use").input
        return [(c["content"], c["confidence"], FactType(c["fact_type"]))
                for c in raw["contributions"]]

    def _post_contributions(self, contributions: list[tuple]):
        for content, confidence, fact_type in contributions:
            fact = self.board.post(self.agent_id, fact_type, content, confidence)
            print(f"  {fact}")
        self._done = True


class SymptomAnalysisAgent(BaseKnowledgeSource):
    """Always eligible first — analyzes the raw patient presentation."""

    def is_eligible(self) -> bool:
        return (
            not self._done and
            self.board.has_fact_type(FactType.SYMPTOM)
        )

    def contribute(self):
        print(f"\n  [{self.agent_id}] Analyzing symptoms...")
        symptoms = [f.content for f in self.board.get_facts(FactType.SYMPTOM)]

        if not USE_LLM:
            self._post_contributions(MOCK_CONTRIBUTIONS[self.agent_id])
            return

        self._post_contributions(self._llm_contribute(
            f"You are a general physician. Analyze these symptoms and post initial hypotheses:\n{symptoms}"
        ))


class DermatologyAgent(BaseKnowledgeSource):
    """Triggers when 'rash' appears in any symptom or hypothesis."""

    def is_eligible(self) -> bool:
        return (
            not self._done and
            self.board.contains_keyword("rash", [FactType.SYMPTOM, FactType.HYPOTHESIS])
        )

    def contribute(self):
        print(f"\n  [{self.agent_id}] Assessing skin findings...")
        evidence = self.board.get_facts(min_confidence=0.5)

        if not USE_LLM:
            self._post_contributions(MOCK_CONTRIBUTIONS[self.agent_id])
            return

        context = "\n".join(f.content for f in evidence)
        self._post_contributions(self._llm_contribute(
            f"You are a dermatologist. Assess the skin-related findings:\n{context}"
        ))


class VirologyAgent(BaseKnowledgeSource):
    """Triggers when 'viral' hypothesis appears with sufficient confidence."""

    def is_eligible(self) -> bool:
        return (
            not self._done and
            self.board.contains_keyword("viral", [FactType.HYPOTHESIS, FactType.ASSESSMENT],
                                        min_confidence=0.65)
        )

    def contribute(self):
        print(f"\n  [{self.agent_id}] Evaluating viral hypothesis...")
        evidence = self.board.get_facts(min_confidence=0.6)

        if not USE_LLM:
            self._post_contributions(MOCK_CONTRIBUTIONS[self.agent_id])
            return

        context = "\n".join(f.content for f in evidence)
        self._post_contributions(self._llm_contribute(
            f"You are a virologist. Evaluate the viral hypothesis and request any needed tests:\n{context}"
        ))


class PathologyAgent(BaseKnowledgeSource):
    """Triggers when a test_request exists on the board."""

    def is_eligible(self) -> bool:
        return (
            not self._done and
            self.board.has_fact_type(FactType.TEST_REQUEST)
        )

    def contribute(self):
        requests = [f.content for f in self.board.get_facts(FactType.TEST_REQUEST)]
        print(f"\n  [{self.agent_id}] Processing lab requests: {len(requests)} test(s)...")

        if not USE_LLM:
            self._post_contributions(MOCK_CONTRIBUTIONS[self.agent_id])
            return

        self._post_contributions(self._llm_contribute(
            f"You are a pathologist. Return realistic lab results for these test requests:\n{requests}\n"
            f"Context: patient with fever and rash, suspected viral exanthem."
        ))


class InfectiousDiseaseAgent(BaseKnowledgeSource):
    """Triggers when lab results AND a viral hypothesis exist — synthesizes diagnosis."""

    def is_eligible(self) -> bool:
        return (
            not self._done and
            self.board.has_fact_type(FactType.LAB_RESULT) and
            self.board.contains_keyword("viral", min_confidence=0.7)
        )

    def contribute(self):
        print(f"\n  [{self.agent_id}] Synthesizing diagnosis from all evidence...")
        all_evidence = self.board.get_facts(min_confidence=0.6)

        if not USE_LLM:
            self._post_contributions(MOCK_CONTRIBUTIONS[self.agent_id])
            return

        context = "\n".join(str(f) for f in all_evidence)
        self._post_contributions(self._llm_contribute(
            f"You are an infectious disease specialist. Review all evidence and post a final diagnosis "
            f"with treatment recommendation:\n{context}"
        ))


# ─────────────────────────────────────────────────────────────
# 4. CONTROLLER — Arbitrates the problem-solving cycles
#    Selects eligible agents, runs them, checks convergence
# ─────────────────────────────────────────────────────────────

class BlackboardController:

    MAX_CYCLES = 8   # safety limit — prevents infinite loops

    def __init__(self, blackboard: Blackboard, knowledge_sources: list):
        self.blackboard        = blackboard
        self.knowledge_sources = knowledge_sources

    def run(self, patient_presentation: str) -> Optional[Fact]:
        print(f"\n{'='*60}")
        print(f"  [Controller] Starting diagnostic session")
        print(f"  Presentation: {patient_presentation}")
        print(f"{'='*60}")

        # Seed the blackboard with the raw patient presentation
        self.blackboard.post(
            agent_id   = "ER_Intake",
            fact_type  = FactType.SYMPTOM,
            content    = patient_presentation,
            confidence = 1.0
        )

        for cycle in range(1, self.MAX_CYCLES + 1):
            print(f"\n── Cycle {cycle} ──────────────────────────────────────")

            # Step 1: Select eligible knowledge sources
            eligible = [ks for ks in self.knowledge_sources if ks.is_eligible()]

            if not eligible:
                print(f"  [Controller] No eligible agents — stopping.")
                break

            print(f"  [Controller] Eligible agents: {[ks.agent_id for ks in eligible]}")

            # Step 2: Each eligible agent contributes to the blackboard
            for ks in eligible:
                ks.contribute()

            # Step 3: Check if we've converged
            if self.blackboard.check_convergence():
                print(f"\n  [Controller] CONVERGENCE REACHED after {cycle} cycle(s).")
                break

            time.sleep(0.1)  # brief pause between cycles

        # Return the highest-confidence diagnosis
        diagnoses = self.blackboard.get_facts(FactType.DIAGNOSIS, min_confidence=0.5)
        return max(diagnoses, key=lambda f: f.confidence) if diagnoses else None


# ─────────────────────────────────────────────────────────────
# 5. DEMO — Run two diagnostic cases
# ─────────────────────────────────────────────────────────────

def print_audit_trail(board: Blackboard):
    print(f"\n{'='*60}")
    print("  BLACKBOARD AUDIT TRAIL  (full chain of thought)")
    print(f"{'='*60}")
    for fact in board.all_facts():
        tag = "★" if fact.fact_type == FactType.DIAGNOSIS else " "
        print(f"  {tag} {fact.fact_id}  {fact}")


if __name__ == "__main__":
    if not USE_LLM:
        print("[DEMO MODE] Running with mock contributions (set ANTHROPIC_API_KEY for real LLM)\n")

    board = Blackboard()

    agents = [
        SymptomAnalysisAgent("SymptomAnalysisAgent", board),
        DermatologyAgent    ("DermatologyAgent",     board),
        VirologyAgent       ("VirologyAgent",        board),
        PathologyAgent      ("PathologyAgent",       board),
        InfectiousDiseaseAgent("InfectiousDiseaseAgent", board),
    ]

    controller = BlackboardController(board, agents)

    final_diagnosis = controller.run(
        "Adult patient, 28F. Day 3 of high fever (39.5°C), widespread red rash "
        "starting on face spreading to trunk, mild conjunctivitis, no recent travel."
    )

    print_audit_trail(board)

    print(f"\n{'='*60}")
    print("  FINAL DIAGNOSIS")
    print(f"{'='*60}")
    if final_diagnosis:
        print(f"  {final_diagnosis.content}")
        print(f"  Confidence: {final_diagnosis.confidence:.0%}")
        print(f"  Posted by:  {final_diagnosis.agent_id}")
    else:
        print("  Insufficient evidence for diagnosis — escalate to specialist review.")
