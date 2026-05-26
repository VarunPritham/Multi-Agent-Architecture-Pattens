"""
Multi-Agent Planning Pattern — Market Analysis Report
------------------------------------------------------
Demonstrates:
  1. Plan as a first-class artifact — structured object with tasks, deps, status
  2. LLM-based goal decomposition (with mock fallback)
  3. Dependency graph — tasks declare what they depend on
  4. Parallel execution — ready tasks (no unmet deps) run concurrently via ThreadPoolExecutor
  5. Sequential gating — dependent tasks wait until all prerequisites complete
  6. Dynamic replanning — if a task fails, orchestrator adapts the plan
  7. Plan visualisation — print the full task DAG with live status
  8. Progress tracking — per-task timing and results

Plan DAG for "Market Analysis Report":

  T1: gather_sales_data          ──────────┐
  T2: analyze_competitor_chatter ──────────┼──→ T4: synthesize_findings ──→ T5: executive_summary
  T3: summarize_analyst_reports  ──────────┘

  T1, T2, T3 → parallel (no dependencies)
  T4          → sequential (waits for T1 + T2 + T3)
  T5          → sequential (waits for T4)
"""

import concurrent.futures
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import anthropic


# ─────────────────────────────────────────────────────────────
# 1. PLAN MODEL — The shared artifact that guides execution
# ─────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING   = "pending"     # waiting for dependencies
    READY     = "ready"       # all dependencies done, can execute
    RUNNING   = "running"     # currently executing
    COMPLETE  = "complete"    # finished successfully
    FAILED    = "failed"      # failed — may trigger replanning
    SKIPPED   = "skipped"     # skipped due to failed dependency


class PlanStatus(str, Enum):
    DRAFT      = "draft"
    EXECUTING  = "executing"
    COMPLETE   = "complete"
    PARTIAL    = "partial"    # some tasks failed but plan produced output
    FAILED     = "failed"


@dataclass
class SubTask:
    task_id:       str
    description:   str
    assigned_agent: str
    depends_on:    list[str]  # task_ids this must wait for
    status:        TaskStatus = TaskStatus.PENDING
    result:        Optional[str] = None
    error:         Optional[str] = None
    started_at:    Optional[str] = None
    completed_at:  Optional[str] = None

    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            fmt = "%H:%M:%S.%f"
            s = datetime.strptime(self.started_at, fmt)
            e = datetime.strptime(self.completed_at, fmt)
            return (e - s).total_seconds()
        return None


@dataclass
class Plan:
    plan_id:    str
    goal:       str
    tasks:      dict[str, SubTask] = field(default_factory=dict)
    status:     PlanStatus = PlanStatus.DRAFT
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_task(self, task: SubTask):
        self.tasks[task.task_id] = task

    def ready_tasks(self) -> list[SubTask]:
        """Tasks whose all dependencies are complete and are themselves pending/ready."""
        ready = []
        for task in self.tasks.values():
            if task.status not in (TaskStatus.PENDING, TaskStatus.READY):
                continue
            deps_done = all(
                self.tasks[dep].status == TaskStatus.COMPLETE
                for dep in task.depends_on
                if dep in self.tasks
            )
            deps_failed = any(
                self.tasks[dep].status in (TaskStatus.FAILED, TaskStatus.SKIPPED)
                for dep in task.depends_on
                if dep in self.tasks
            )
            if deps_failed:
                task.status = TaskStatus.SKIPPED  # cascade skip
            elif deps_done:
                task.status = TaskStatus.READY
                ready.append(task)
        return ready

    def is_complete(self) -> bool:
        return all(
            t.status in (TaskStatus.COMPLETE, TaskStatus.FAILED, TaskStatus.SKIPPED)
            for t in self.tasks.values()
        )

    def successful_results(self) -> dict[str, str]:
        return {
            t.task_id: t.result
            for t in self.tasks.values()
            if t.status == TaskStatus.COMPLETE and t.result
        }


# ─────────────────────────────────────────────────────────────
# 2. SPECIALISED WORKER AGENTS — Each owns one research domain
# ─────────────────────────────────────────────────────────────

USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))
client  = anthropic.Anthropic() if USE_LLM else None

MOCK_RESULTS = {
    "DataRetrieverAgent": (
        "Sales data retrieved: Q1 $2.1M (+18% YoY), Q2 $2.4M (+22% YoY). "
        "Top markets: North America (45%), Europe (30%), APAC (25%). "
        "Product X leads category with 34% market share."
    ),
    "SocialMediaAgent": (
        "Competitor analysis: CompetitorA launched v2.0 last month — mixed reception. "
        "Social sentiment for Product X: 72% positive. "
        "Key themes: reliability praised, pricing questioned. "
        "Share of voice: Product X 41%, CompetitorA 35%, Others 24%."
    ),
    "FinancialDocsAgent": (
        "Analyst consensus: 4 Buy, 1 Hold, 0 Sell. Price target $145 (current $128). "
        "TAM estimated at $8.2B growing at 14% CAGR. "
        "Product X well-positioned in premium segment. "
        "Key risk: commoditisation pressure from low-cost entrants."
    ),
    "ReportWriterAgent": (
        "MARKET ANALYSIS REPORT — Product X\n\n"
        "EXECUTIVE BRIEF: Product X demonstrates strong momentum with 34% market share "
        "and consistent double-digit revenue growth. Analyst sentiment is bullish "
        "(4 Buy ratings, $145 price target). Social media presence is healthy at 72% "
        "positive sentiment. Primary risk is pricing pressure from emerging competitors.\n\n"
        "REVENUE PERFORMANCE: Q1 $2.1M (+18%), Q2 $2.4M (+22%). North America remains "
        "the dominant market at 45% of revenue.\n\n"
        "COMPETITIVE LANDSCAPE: CompetitorA's v2.0 launch has been mixed. Product X "
        "holds a 6-point voice-of-share lead.\n\n"
        "RECOMMENDATIONS: Maintain premium positioning. Accelerate APAC expansion. "
        "Address pricing perception via value-communication campaign."
    ),
    "SummaryAgent": (
        "EXECUTIVE SUMMARY (3 bullets):\n"
        "• Product X is growing 20% YoY with 34% market share — category leader\n"
        "• Analyst consensus is bullish; $145 price target implies 13% upside\n"
        "• Priority actions: reinforce value messaging on pricing, accelerate APAC"
    ),
}


class BaseWorkerAgent:
    agent_id: str

    def run(self, task_description: str, context: dict = None) -> str:
        if not USE_LLM:
            print(f"    [{self.agent_id}] [DEMO] Running task: {task_description[:60]}...")
            time.sleep(0.3)  # simulate work
            return MOCK_RESULTS.get(self.agent_id, f"[{self.agent_id}] Result for: {task_description}")

        ctx_str = "\n".join(f"{k}: {v[:200]}" for k, v in (context or {}).items())
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": (
                f"You are a {self.agent_id}. Complete this research task:\n"
                f"Task: {task_description}\n"
                f"{'Context from previous tasks:\n' + ctx_str if ctx_str else ''}\n"
                f"Provide a concise, factual result (3–5 sentences)."
            )}]
        )
        return response.content[0].text


class DataRetrieverAgent(BaseWorkerAgent):
    agent_id = "DataRetrieverAgent"

class SocialMediaAgent(BaseWorkerAgent):
    agent_id = "SocialMediaAgent"

class FinancialDocsAgent(BaseWorkerAgent):
    agent_id = "FinancialDocsAgent"

class ReportWriterAgent(BaseWorkerAgent):
    agent_id = "ReportWriterAgent"

class SummaryAgent(BaseWorkerAgent):
    agent_id = "SummaryAgent"

AGENT_REGISTRY: dict[str, BaseWorkerAgent] = {
    "DataRetrieverAgent": DataRetrieverAgent(),
    "SocialMediaAgent":   SocialMediaAgent(),
    "FinancialDocsAgent": FinancialDocsAgent(),
    "ReportWriterAgent":  ReportWriterAgent(),
    "SummaryAgent":       SummaryAgent(),
}


# ─────────────────────────────────────────────────────────────
# 3. PLANNING AGENT — Decomposes a goal into a structured plan
# ─────────────────────────────────────────────────────────────

class PlanningAgent:
    """
    Takes a high-level goal and produces a Plan with tasks,
    dependencies, and agent assignments.
    Uses LLM for dynamic decomposition (mock for demo).
    """

    def decompose(self, goal: str, available_agents: list[str]) -> Plan:
        print(f"\n  [PlanningAgent] Decomposing goal: '{goal}'")

        if not USE_LLM:
            return self._mock_decompose(goal)
        return self._llm_decompose(goal, available_agents)

    def _mock_decompose(self, goal: str) -> Plan:
        """Fixed plan for the market analysis demo."""
        print(f"  [PlanningAgent] [DEMO] Generating plan...")
        plan = Plan(plan_id="PLAN-001", goal=goal)

        plan.add_task(SubTask("T1", "Retrieve sales data and market share metrics",
                              "DataRetrieverAgent", depends_on=[]))
        plan.add_task(SubTask("T2", "Analyse competitor social media chatter and sentiment",
                              "SocialMediaAgent", depends_on=[]))
        plan.add_task(SubTask("T3", "Summarise analyst reports and financial forecasts",
                              "FinancialDocsAgent", depends_on=[]))
        plan.add_task(SubTask("T4", "Synthesise all findings and draft the full report",
                              "ReportWriterAgent", depends_on=["T1", "T2", "T3"]))
        plan.add_task(SubTask("T5", "Write a 3-bullet executive summary from the report",
                              "SummaryAgent", depends_on=["T4"]))
        return plan

    def _llm_decompose(self, goal: str, available_agents: list[str]) -> Plan:
        """Dynamic LLM-based decomposition — produces different plans for different goals."""
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=[{
                "name": "create_plan",
                "description": "Create a structured execution plan for the given goal",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tasks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "task_id":       {"type": "string"},
                                    "description":   {"type": "string"},
                                    "assigned_agent":{"type": "string",
                                                     "enum": available_agents},
                                    "depends_on":    {"type": "array",
                                                     "items": {"type": "string"}}
                                },
                                "required": ["task_id", "description",
                                             "assigned_agent", "depends_on"]
                            }
                        }
                    },
                    "required": ["tasks"]
                }
            }],
            tool_choice={"type": "tool", "name": "create_plan"},
            messages=[{"role": "user", "content": (
                f"Decompose this goal into a plan of 4–6 sub-tasks:\n\n"
                f"Goal: {goal}\n\n"
                f"Available agents: {available_agents}\n\n"
                f"Rules:\n"
                f"- Each task must be assigned to exactly one available agent\n"
                f"- Task IDs must be T1, T2, ... in order\n"
                f"- depends_on lists task_ids that must complete before this task starts\n"
                f"- Independent tasks (empty depends_on) will run in parallel\n"
                f"- The final task should synthesise all findings"
            )}]
        )
        raw = next(b for b in response.content if b.type == "tool_use").input
        plan = Plan(plan_id="PLAN-001", goal=goal)
        for t in raw["tasks"]:
            plan.add_task(SubTask(
                task_id        = t["task_id"],
                description    = t["description"],
                assigned_agent = t["assigned_agent"],
                depends_on     = t["depends_on"]
            ))
        return plan


# ─────────────────────────────────────────────────────────────
# 4. PLAN EXECUTOR — Executes the plan respecting dependencies
# ─────────────────────────────────────────────────────────────

class PlanExecutor:

    MAX_WORKERS = 4    # max parallel tasks

    def execute(self, plan: Plan) -> dict:
        plan.status = PlanStatus.EXECUTING
        print(f"\n{'─'*60}")
        print(f"  [PlanExecutor] Executing plan: {plan.plan_id}")
        print_plan(plan)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures: dict[concurrent.futures.Future, SubTask] = {}

            while not plan.is_complete():
                # Find tasks that are now ready to run
                ready = [t for t in plan.ready_tasks() if t.status == TaskStatus.READY]

                # Submit all ready tasks to the thread pool
                for task in ready:
                    if task.task_id not in {f_task.task_id for f_task in futures.values()}:
                        task.status = TaskStatus.RUNNING
                        task.started_at = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        print(f"\n  ▶ [{task.task_id}] Starting: {task.description[:55]}..."
                              f"\n      Agent: {task.assigned_agent}"
                              f"  |  Deps: {task.depends_on or 'none'}")

                        context = plan.successful_results()
                        future = executor.submit(
                            self._run_task, task, context
                        )
                        futures[future] = task

                if not futures:
                    break  # nothing running and nothing ready → stuck

                # Wait for at least one task to finish
                done, _ = concurrent.futures.wait(
                    futures.keys(), return_when=concurrent.futures.FIRST_COMPLETED
                )

                for future in done:
                    task = futures.pop(future)
                    task.completed_at = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    try:
                        task.result = future.result()
                        task.status = TaskStatus.COMPLETE
                        dur = task.duration_seconds()
                        print(f"\n  ✓ [{task.task_id}] Complete ({dur:.1f}s): "
                              f"{task.result[:80]}...")
                    except Exception as e:
                        task.status = TaskStatus.FAILED
                        task.error = str(e)
                        print(f"\n  ✗ [{task.task_id}] FAILED: {e}")
                        self._replan(plan, task)

        # Determine overall plan status
        failed  = [t for t in plan.tasks.values() if t.status == TaskStatus.FAILED]
        skipped = [t for t in plan.tasks.values() if t.status == TaskStatus.SKIPPED]
        plan.status = (
            PlanStatus.FAILED   if len(failed) == len(plan.tasks) else
            PlanStatus.PARTIAL  if failed or skipped else
            PlanStatus.COMPLETE
        )
        return plan.successful_results()

    def _run_task(self, task: SubTask, context: dict) -> str:
        agent = AGENT_REGISTRY.get(task.assigned_agent)
        if not agent:
            raise ValueError(f"No agent registered for '{task.assigned_agent}'")
        return agent.run(task.description, context)

    def _replan(self, plan: Plan, failed_task: SubTask):
        """
        Dynamic replanning on failure.
        Strategy: mark dependent tasks as skipped, log the adaptation.
        In production: could re-decompose the remaining goal or reassign to a backup agent.
        """
        affected = [
            t for t in plan.tasks.values()
            if failed_task.task_id in t.depends_on and t.status == TaskStatus.PENDING
        ]
        if affected:
            print(f"  [PlanExecutor] Replanning — cascading skip to: "
                  f"{[t.task_id for t in affected]}")
            for t in affected:
                t.status = TaskStatus.SKIPPED
                t.error  = f"Skipped: dependency {failed_task.task_id} failed"


# ─────────────────────────────────────────────────────────────
# 5. ORCHESTRATOR — Ties planning and execution together
# ─────────────────────────────────────────────────────────────

class MarketAnalysisOrchestrator:

    def __init__(self):
        self.planner  = PlanningAgent()
        self.executor = PlanExecutor()

    def generate_report(self, product_name: str,
                        inject_failure: str = None) -> str:
        goal = f"Generate a comprehensive market analysis report for {product_name}"

        # Step 1: Decompose goal into plan
        plan = self.planner.decompose(goal, list(AGENT_REGISTRY.keys()))

        # Optionally inject a failure for the replanning demo
        if inject_failure and inject_failure in plan.tasks:
            _patch_agent_for_failure(inject_failure)

        # Step 2: Execute the plan
        results = self.executor.execute(plan)

        # Step 3: Summarise outcome
        print_plan_summary(plan)

        # Return the final output (last synthesis task's result)
        synthesis_tasks = [t for t in plan.tasks.values()
                           if not any(plan.tasks.get(other, SubTask("", "", "", []))
                                      .depends_on.__contains__(t.task_id)
                                      for other in plan.tasks)
                           and t.status == TaskStatus.COMPLETE]
        if synthesis_tasks:
            return synthesis_tasks[-1].result or "No result produced."
        return "Plan completed with partial results."


# ─────────────────────────────────────────────────────────────
# 6. HELPERS — Visualisation and failure injection
# ─────────────────────────────────────────────────────────────

STATUS_ICON = {
    TaskStatus.PENDING:  "○",
    TaskStatus.READY:    "◎",
    TaskStatus.RUNNING:  "●",
    TaskStatus.COMPLETE: "✓",
    TaskStatus.FAILED:   "✗",
    TaskStatus.SKIPPED:  "⊘",
}


def print_plan(plan: Plan):
    print(f"\n  Plan: {plan.goal}")
    for task in plan.tasks.values():
        icon  = STATUS_ICON[task.status]
        deps  = f"← {task.depends_on}" if task.depends_on else "← (parallel)"
        print(f"  {icon} [{task.task_id}] {task.description[:50]:50s}  "
              f"[{task.assigned_agent}]  {deps}")


def print_plan_summary(plan: Plan):
    print(f"\n{'='*60}")
    print(f"  PLAN SUMMARY — {plan.status.upper()}")
    print(f"{'='*60}")
    for task in plan.tasks.values():
        icon = STATUS_ICON[task.status]
        dur  = f"{task.duration_seconds():.1f}s" if task.duration_seconds() else "—"
        print(f"  {icon} [{task.task_id}] {task.assigned_agent:25s} "
              f"status={task.status:8s}  time={dur}")


def _patch_agent_for_failure(task_id_to_fail: str):
    """Monkey-patches an agent to throw on its next run call — for replanning demo."""
    import types

    # Find which agent is assigned to that task in the default plan
    task_agent_map = {
        "T2": "SocialMediaAgent",
        "T1": "DataRetrieverAgent",
        "T3": "FinancialDocsAgent",
    }
    agent_name = task_agent_map.get(task_id_to_fail)
    if not agent_name or agent_name not in AGENT_REGISTRY:
        return
    agent = AGENT_REGISTRY[agent_name]
    original_run = agent.run

    def failing_run(self, *args, **kwargs):
        raise RuntimeError(f"API rate limit exceeded for {agent_name}")

    agent.run = types.MethodType(failing_run, agent)


# ─────────────────────────────────────────────────────────────
# 7. DEMO
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not USE_LLM:
        print("[DEMO MODE] Running with mock agent results "
              "(set ANTHROPIC_API_KEY for real LLM)\n")

    orchestrator = MarketAnalysisOrchestrator()

    # ── Demo 1: Full happy path ──────────────────────────────
    print(f"\n{'='*60}")
    print("  DEMO 1: Full happy-path plan execution")
    print(f"{'='*60}")
    report = orchestrator.generate_report("Product X")
    print(f"\n  FINAL OUTPUT:\n{'─'*40}")
    print(f"  {report[:400]}...")

    # ── Demo 2: Dynamic replanning (T2 fails) ───────────────
    print(f"\n\n{'='*60}")
    print("  DEMO 2: Dynamic replanning — T2 (SocialMediaAgent) fails")
    print(f"{'='*60}")
    report2 = orchestrator.generate_report("Product Y", inject_failure="T2")
    print(f"\n  FINAL OUTPUT:\n{'─'*40}")
    print(f"  {report2[:300]}...")
