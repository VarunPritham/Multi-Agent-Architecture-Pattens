"""
Supervisor (Orchestrator) Architecture — Loan Approval Example
--------------------------------------------------------------
Demonstrates:
  1. Central orchestrator that coordinates without doing domain work
  2. Specialized worker agents with strict Pydantic output schemas
  3. Conditional branching at the orchestrator level
  4. Checkpointing — state persistence after every step so the
     workflow can resume after a crash
  5. Fault handling — orchestrator catches worker failures and decides
     whether to retry, reject, or escalate

Workflow:
  User → LoanOrchestratorAgent
              ↓
      DocumentValidationAgent   (step 1)
              ↓ (if valid)
        CreditCheckAgent        (step 2)
              ↓ (if score ≥ 600)
      RiskAssessmentAgent       (step 3)
              ↓
         Final Decision         (step 4)
"""

import anthropic
import json
import os
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel
from typing import Optional

client = anthropic.Anthropic()

# ─────────────────────────────────────────────────────────────
# 1. SHARED DATA MODELS — The "contracts" between agents.
#    Every agent speaks this language. No free-text handoffs.
# ─────────────────────────────────────────────────────────────

class LoanApplication(BaseModel):
    applicant_id: str
    name: str
    annual_income: float
    loan_amount: float
    loan_purpose: str
    documents_provided: list[str]  # e.g. ["pay_stub", "tax_return", "id"]


class ValidationResult(BaseModel):
    status: str            # "valid" | "invalid"
    missing_docs: list[str]
    notes: str


class CreditReport(BaseModel):
    score: int             # 300 – 850
    payment_history: str   # "excellent" | "good" | "fair" | "poor"
    existing_debts: float
    notes: str


class RiskAssessment(BaseModel):
    risk_level: str        # "low" | "medium" | "high"
    debt_to_income_ratio: float
    recommendation: str    # "approve" | "approve_with_conditions" | "reject"
    conditions: list[str]  # e.g. ["require co-signer", "reduce loan amount"]
    notes: str


class LoanDecision(BaseModel):
    application_id: str
    decision: str          # "approved" | "approved_with_conditions" | "rejected"
    reason: str
    conditions: list[str]
    timestamp: str


# ─────────────────────────────────────────────────────────────
# 2. WORKER AGENTS — Each owns one domain. Returns structured data.
#    These use Claude to simulate realistic domain intelligence.
# ─────────────────────────────────────────────────────────────

class DocumentValidationAgent:
    """Checks that all required documents are present and consistent."""

    REQUIRED_DOCS = {"pay_stub", "tax_return", "id", "bank_statement"}

    def validate(self, application: LoanApplication) -> ValidationResult:
        print(f"  [DocumentValidationAgent] Validating documents for {application.name}...")

        provided = set(application.documents_provided)
        missing = list(self.REQUIRED_DOCS - provided)

        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(f"  [DEMO MODE] Simulating document validation")
            status = "invalid" if missing else "valid"
            return ValidationResult(
                status=status,
                missing_docs=missing,
                notes=f"{'Missing required documents: ' + str(missing) if missing else 'All required documents present and verified.'}"
            )

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            tools=[{
                "name": "return_validation_result",
                "description": "Return the document validation result",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status":       {"type": "string", "enum": ["valid", "invalid"]},
                        "missing_docs": {"type": "array", "items": {"type": "string"}},
                        "notes":        {"type": "string"}
                    },
                    "required": ["status", "missing_docs", "notes"]
                }
            }],
            tool_choice={"type": "tool", "name": "return_validation_result"},
            messages=[{
                "role": "user",
                "content": (
                    f"Validate this loan application's documents.\n"
                    f"Applicant: {application.name}\n"
                    f"Provided: {application.documents_provided}\n"
                    f"Missing: {missing}\n"
                    f"Income: ${application.annual_income:,.0f} | Loan: ${application.loan_amount:,.0f}\n"
                    f"Status is 'invalid' only if there are missing docs. Write a brief note."
                )
            }]
        )

        result = next(b for b in response.content if b.type == "tool_use").input
        return ValidationResult(**result)


class CreditCheckAgent:
    """Retrieves and evaluates the applicant's credit profile."""

    def check(self, applicant_id: str, application: LoanApplication) -> CreditReport:
        print(f"  [CreditCheckAgent] Running credit check for applicant {applicant_id}...")

        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(f"  [DEMO MODE] Simulating credit check")
            # Derive a plausible score from income/loan ratio for demo variety
            ratio = application.annual_income / application.loan_amount
            score = min(850, int(550 + ratio * 80))
            history = "excellent" if score > 750 else "good" if score > 680 else "fair" if score > 620 else "poor"
            debts = application.annual_income * 0.12
            return CreditReport(
                score=score,
                payment_history=history,
                existing_debts=debts,
                notes=f"Credit profile consistent with income level. Score {score} reflects payment history and debt load."
            )

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            tools=[{
                "name": "return_credit_report",
                "description": "Return the credit check result",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "score":            {"type": "integer", "minimum": 300, "maximum": 850},
                        "payment_history":  {"type": "string", "enum": ["excellent", "good", "fair", "poor"]},
                        "existing_debts":   {"type": "number"},
                        "notes":            {"type": "string"}
                    },
                    "required": ["score", "payment_history", "existing_debts", "notes"]
                }
            }],
            tool_choice={"type": "tool", "name": "return_credit_report"},
            messages=[{
                "role": "user",
                "content": (
                    f"Simulate a realistic credit check for this applicant.\n"
                    f"Applicant ID: {applicant_id}\n"
                    f"Name: {application.name}\n"
                    f"Annual Income: ${application.annual_income:,.0f}\n"
                    f"Loan Requested: ${application.loan_amount:,.0f}\n"
                    f"Purpose: {application.loan_purpose}\n\n"
                    f"Generate a plausible credit score (300-850), payment history, "
                    f"existing debt total, and a brief note."
                )
            }]
        )

        result = next(b for b in response.content if b.type == "tool_use").input
        return CreditReport(**result)


class RiskAssessmentAgent:
    """Combines financial data to produce a risk rating and recommendation."""

    def assess(self, application: LoanApplication, credit: CreditReport) -> RiskAssessment:
        print(f"  [RiskAssessmentAgent] Assessing risk for {application.name}...")

        dti = (credit.existing_debts + application.loan_amount * 0.05) / application.annual_income

        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(f"  [DEMO MODE] Simulating risk assessment")
            if dti < 0.35 and credit.score >= 700:
                risk, rec, conditions = "low", "approve", []
            elif dti < 0.50 and credit.score >= 640:
                risk, rec, conditions = "medium", "approve_with_conditions", ["Provide 6 months of bank statements", "Interest rate premium applies"]
            else:
                risk, rec, conditions = "high", "reject", []
            return RiskAssessment(
                risk_level=risk,
                debt_to_income_ratio=dti,
                recommendation=rec,
                conditions=conditions,
                notes=f"DTI of {dti:.1%} with credit score {credit.score}. Risk classified as {risk}."
            )

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            tools=[{
                "name": "return_risk_assessment",
                "description": "Return the risk assessment result",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "risk_level":           {"type": "string", "enum": ["low", "medium", "high"]},
                        "debt_to_income_ratio": {"type": "number"},
                        "recommendation":       {"type": "string", "enum": ["approve", "approve_with_conditions", "reject"]},
                        "conditions":           {"type": "array", "items": {"type": "string"}},
                        "notes":                {"type": "string"}
                    },
                    "required": ["risk_level", "debt_to_income_ratio", "recommendation", "conditions", "notes"]
                }
            }],
            tool_choice={"type": "tool", "name": "return_risk_assessment"},
            messages=[{
                "role": "user",
                "content": (
                    f"Perform a risk assessment for this loan application.\n"
                    f"Applicant: {application.name}\n"
                    f"Annual Income: ${application.annual_income:,.0f}\n"
                    f"Loan Amount: ${application.loan_amount:,.0f}\n"
                    f"Purpose: {application.loan_purpose}\n"
                    f"Credit Score: {credit.score}\n"
                    f"Payment History: {credit.payment_history}\n"
                    f"Existing Debts: ${credit.existing_debts:,.0f}\n"
                    f"Calculated DTI: {dti:.2%}\n\n"
                    f"Assess risk level, provide a recommendation, list any conditions "
                    f"(e.g. co-signer, reduced amount), and write a brief note."
                )
            }]
        )

        result = next(b for b in response.content if b.type == "tool_use").input
        result["debt_to_income_ratio"] = dti  # use our calculated value, not LLM's
        return RiskAssessment(**result)


# ─────────────────────────────────────────────────────────────
# 3. LOAN ORCHESTRATOR — Coordinates everything.
#    Knows the SEQUENCE and RULES. Does zero domain work itself.
# ─────────────────────────────────────────────────────────────

class LoanOrchestratorAgent:

    CHECKPOINT_DIR = Path("/Users/varunpritham/Me and Claude/Multi Agent Architectures/.checkpoints")

    def __init__(self):
        # Instantiate workers — orchestrator owns their lifecycle
        self.doc_validator  = DocumentValidationAgent()
        self.credit_checker = CreditCheckAgent()
        self.risk_assessor  = RiskAssessmentAgent()
        self.CHECKPOINT_DIR.mkdir(exist_ok=True)

    # ── Checkpointing ───────────────────────────────────────
    # Saves state after every step. If the orchestrator crashes
    # between step 2 and 3, we resume from the saved step 2 result.

    def _save_checkpoint(self, app_id: str, step: str, data: dict):
        path = self.CHECKPOINT_DIR / f"{app_id}.json"
        state = json.loads(path.read_text()) if path.exists() else {}
        state[step] = data
        path.write_text(json.dumps(state, indent=2))
        print(f"  [Checkpoint] Saved state after step: {step}")

    def _load_checkpoint(self, app_id: str) -> dict:
        path = self.CHECKPOINT_DIR / f"{app_id}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    # ── Main Workflow ────────────────────────────────────────

    def handle_loan_application(self, application: LoanApplication) -> LoanDecision:
        app_id = application.applicant_id
        print(f"\n{'='*60}")
        print(f"  [Orchestrator] Processing loan for {application.name}")
        print(f"  Loan: ${application.loan_amount:,.0f} | Purpose: {application.loan_purpose}")
        print(f"{'='*60}")

        # Resume from checkpoint if available (crash recovery)
        checkpoint = self._load_checkpoint(app_id)
        if checkpoint:
            print(f"  [Orchestrator] Resuming from checkpoint (steps done: {list(checkpoint.keys())})")

        # ── Step 1: Document Validation ──────────────────────
        if "validation" not in checkpoint:
            print(f"\n[Step 1] Document Validation")
            try:
                validation = self.doc_validator.validate(application)
            except Exception as e:
                return self._reject(app_id, f"Document validation failed: {e}")

            self._save_checkpoint(app_id, "validation", validation.model_dump())
        else:
            validation = ValidationResult(**checkpoint["validation"])
            print(f"\n[Step 1] Document Validation (from checkpoint)")

        print(f"  → Status: {validation.status} | Missing: {validation.missing_docs or 'none'}")

        # Orchestrator's conditional logic — halt if invalid
        if validation.status != "valid":
            return self._reject(app_id, f"Invalid documents. Missing: {validation.missing_docs}")

        # ── Step 2: Credit Check ─────────────────────────────
        if "credit" not in checkpoint:
            print(f"\n[Step 2] Credit Check")
            try:
                credit = self.credit_checker.check(app_id, application)
            except Exception as e:
                return self._reject(app_id, f"Credit check failed: {e}")

            self._save_checkpoint(app_id, "credit", credit.model_dump())
        else:
            credit = CreditReport(**checkpoint["credit"])
            print(f"\n[Step 2] Credit Check (from checkpoint)")

        print(f"  → Score: {credit.score} | History: {credit.payment_history} | Debts: ${credit.existing_debts:,.0f}")

        # Orchestrator's conditional logic — halt if score too low
        if credit.score < 600:
            return self._reject(app_id, f"Credit score {credit.score} is below minimum threshold of 600.")

        # ── Step 3: Risk Assessment ──────────────────────────
        if "risk" not in checkpoint:
            print(f"\n[Step 3] Risk Assessment")
            try:
                risk = self.risk_assessor.assess(application, credit)
            except Exception as e:
                return self._reject(app_id, f"Risk assessment failed: {e}")

            self._save_checkpoint(app_id, "risk", risk.model_dump())
        else:
            risk = RiskAssessment(**checkpoint["risk"])
            print(f"\n[Step 3] Risk Assessment (from checkpoint)")

        print(f"  → Risk: {risk.risk_level} | DTI: {risk.debt_to_income_ratio:.1%} | Recommendation: {risk.recommendation}")

        # ── Step 4: Final Decision ───────────────────────────
        print(f"\n[Step 4] Final Decision")
        decision = self._make_final_decision(app_id, risk)
        print(f"  → Decision: {decision.decision.upper()}")
        if decision.conditions:
            print(f"  → Conditions: {', '.join(decision.conditions)}")

        # Clean up checkpoint on successful completion
        checkpoint_path = self.CHECKPOINT_DIR / f"{app_id}.json"
        if checkpoint_path.exists():
            checkpoint_path.unlink()

        return decision

    def _make_final_decision(self, app_id: str, risk: RiskAssessment) -> LoanDecision:
        decision_map = {
            "approve":                 "approved",
            "approve_with_conditions": "approved_with_conditions",
            "reject":                  "rejected",
        }
        return LoanDecision(
            application_id=app_id,
            decision=decision_map[risk.recommendation],
            reason=risk.notes,
            conditions=risk.conditions,
            timestamp=datetime.now().isoformat()
        )

    def _reject(self, app_id: str, reason: str) -> LoanDecision:
        print(f"\n  [Orchestrator] REJECTING — {reason}")
        return LoanDecision(
            application_id=app_id,
            decision="rejected",
            reason=reason,
            conditions=[],
            timestamp=datetime.now().isoformat()
        )


# ─────────────────────────────────────────────────────────────
# 4. DEMO — Three applicants: approval, rejection, borderline
# ─────────────────────────────────────────────────────────────

def print_decision(decision: LoanDecision):
    border = "✓" if "approved" in decision.decision else "✗"
    print(f"\n{'─'*60}")
    print(f"  FINAL DECISION: {border} {decision.decision.upper()}")
    print(f"  Reason:    {decision.reason}")
    if decision.conditions:
        print(f"  Conditions: {', '.join(decision.conditions)}")
    print(f"  Timestamp: {decision.timestamp}")
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    orchestrator = LoanOrchestratorAgent()

    applications = [
        # Case 1: Strong applicant — likely approval
        LoanApplication(
            applicant_id="APP-001",
            name="Sarah Chen",
            annual_income=120_000,
            loan_amount=45_000,
            loan_purpose="Home renovation",
            documents_provided=["pay_stub", "tax_return", "id", "bank_statement"]
        ),
        # Case 2: Missing documents — immediate rejection at step 1
        LoanApplication(
            applicant_id="APP-002",
            name="Marcus Johnson",
            annual_income=85_000,
            loan_amount=30_000,
            loan_purpose="Business expansion",
            documents_provided=["pay_stub", "id"]  # missing tax_return + bank_statement
        ),
        # Case 3: All docs present but high loan relative to income — borderline
        LoanApplication(
            applicant_id="APP-003",
            name="Priya Sharma",
            annual_income=55_000,
            loan_amount=200_000,
            loan_purpose="Real estate investment",
            documents_provided=["pay_stub", "tax_return", "id", "bank_statement"]
        ),
    ]

    for app in applications:
        decision = orchestrator.handle_loan_application(app)
        print_decision(decision)
