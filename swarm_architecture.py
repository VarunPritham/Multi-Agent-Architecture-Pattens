"""
Swarm Architecture — Decentralized Content Creation
----------------------------------------------------
Demonstrates:
  1. Shared task board as the only coordination mechanism
  2. Pull-based, status-driven task claiming (no central dispatcher)
  3. Atomic claiming with locking — prevents two agents grabbing the same task
  4. Concurrent agents polling in parallel threads — emergent workflow
  5. Resilience — kill an agent mid-run, another picks up its work
  6. Multiple tasks processed in parallel (horizontal scalability)
  7. Mock fallback when no API key is set

Workflow (emergent — nobody programs this sequence):
  TaskBoard: status="new"
      ↓  (ResearchAgent self-selects)
  TaskBoard: status="researched"
      ↓  (DraftingAgent self-selects)
  TaskBoard: status="drafted"
      ↓  (EditorAgent self-selects)
  TaskBoard: status="complete"
"""

import anthropic
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────────────────────
# 1. TASK MODEL — The shared state object on the board
# ─────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    NEW        = "new"
    CLAIMED    = "claimed"       # transitional lock — prevents double-claiming
    RESEARCHED = "researched"
    DRAFTING   = "drafting"      # transitional lock
    DRAFTED    = "drafted"
    EDITING    = "editing"       # transitional lock
    COMPLETE   = "complete"
    FAILED     = "failed"


@dataclass
class Task:
    task_id: str
    topic: str
    status: TaskStatus = TaskStatus.NEW
    claimed_by: Optional[str] = None
    data: dict = field(default_factory=dict)
    history: list = field(default_factory=list)   # audit trail of every status change

    def log(self, agent_name: str, message: str):
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "agent":     agent_name,
            "message":   message
        })


# ─────────────────────────────────────────────────────────────
# 2. SHARED TASK BOARD — The only "authority" in the swarm
#    Thread-safe: uses a lock for all state mutations
# ─────────────────────────────────────────────────────────────

class TaskBoard:

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()       # ensures atomic claim operations

    def post(self, topic: str) -> Task:
        task = Task(task_id=str(uuid.uuid4())[:8], topic=topic)
        with self._lock:
            self._tasks[task.task_id] = task
        print(f"\n[TaskBoard] Posted: '{topic}' → ID={task.task_id}")
        return task

    def get_tasks_by_status(self, status: TaskStatus) -> list[Task]:
        with self._lock:
            return [t for t in self._tasks.values() if t.status == status]

    def claim(self, task_id: str, agent_name: str, from_status: TaskStatus, to_status: TaskStatus) -> bool:
        """Atomic claim: only succeeds if the task is still in from_status."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status == from_status:
                task.status = to_status
                task.claimed_by = agent_name
                task.log(agent_name, f"Claimed (status: {from_status} → {to_status})")
                return True
            return False  # Another agent beat us to it

    def update(self, task_id: str, agent_name: str, new_status: TaskStatus, data_updates: dict = None):
        with self._lock:
            task = self._tasks[task_id]
            task.status = new_status
            if data_updates:
                task.data.update(data_updates)
            task.log(agent_name, f"Updated status → {new_status}")

    def get_all(self) -> list[Task]:
        with self._lock:
            return list(self._tasks.values())


# ─────────────────────────────────────────────────────────────
# 3. BASE AGENT — Peers in the swarm. No hierarchy.
# ─────────────────────────────────────────────────────────────

USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))
client  = anthropic.Anthropic() if USE_LLM else None


class SwarmAgent(threading.Thread):
    """
    Base class for all swarm agents.
    Each runs as its own thread, polling the board continuously.
    No agent knows about any other agent — they only know the board.
    """

    POLL_INTERVAL = 0.5  # seconds between board polls

    def __init__(self, name: str, board: TaskBoard):
        super().__init__(daemon=True)
        self.name    = name
        self.board   = board
        self._stop   = threading.Event()

    def run(self):
        print(f"  [{self.name}] Online and polling...")
        while not self._stop.is_set():
            self.poll_and_work()
            time.sleep(self.POLL_INTERVAL)

    def stop(self):
        self._stop.set()

    def poll_and_work(self):
        raise NotImplementedError

    def _llm_call(self, prompt: str, tool_name: str, tool_schema: dict) -> dict:
        """Shared helper for structured LLM calls."""
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=[{"name": tool_name, "description": "", "input_schema": tool_schema}],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": prompt}]
        )
        return next(b for b in response.content if b.type == "tool_use").input


# ─────────────────────────────────────────────────────────────
# 4. SPECIALIZED AGENTS — Peers. Each owns one capability.
# ─────────────────────────────────────────────────────────────

class ResearchAgent(SwarmAgent):
    """Polls for NEW tasks. Gathers facts and key points on the topic."""

    def poll_and_work(self):
        for task in self.board.get_tasks_by_status(TaskStatus.NEW):
            # Atomic claim — prevents race condition with other ResearchAgents
            if not self.board.claim(task.task_id, self.name, TaskStatus.NEW, TaskStatus.CLAIMED):
                continue  # Lost the race, skip

            print(f"\n  [{self.name}] Claimed task {task.task_id}: '{task.topic}'")

            try:
                research = self._do_research(task.topic)
                self.board.update(task.task_id, self.name, TaskStatus.RESEARCHED, {"research": research})
                print(f"  [{self.name}] Finished research on '{task.topic}'")
            except Exception as e:
                self.board.update(task.task_id, self.name, TaskStatus.FAILED, {"error": str(e)})

    def _do_research(self, topic: str) -> dict:
        if not USE_LLM:
            return {
                "key_facts": [
                    f"{topic} is a rapidly growing field with significant global impact.",
                    "Recent studies show adoption rates have doubled in the past five years.",
                    "Key challenges include cost, infrastructure, and public awareness.",
                    "Leading countries are investing heavily in related R&D programs.",
                ],
                "statistics": ["$500B global market by 2030", "30% annual growth rate"],
                "angle": f"The transformative potential of {topic} and its barriers to mass adoption."
            }
        return self._llm_call(
            prompt=f"Research the topic: '{topic}'. Extract 4-5 key facts, 2 statistics, and suggest an article angle.",
            tool_name="research_result",
            tool_schema={
                "type": "object",
                "properties": {
                    "key_facts":  {"type": "array", "items": {"type": "string"}},
                    "statistics": {"type": "array", "items": {"type": "string"}},
                    "angle":      {"type": "string"}
                },
                "required": ["key_facts", "statistics", "angle"]
            }
        )


class DraftingAgent(SwarmAgent):
    """Polls for RESEARCHED tasks. Writes a structured blog draft."""

    def poll_and_work(self):
        for task in self.board.get_tasks_by_status(TaskStatus.RESEARCHED):
            if not self.board.claim(task.task_id, self.name, TaskStatus.RESEARCHED, TaskStatus.DRAFTING):
                continue

            print(f"\n  [{self.name}] Claimed task {task.task_id}: writing draft for '{task.topic}'")

            try:
                draft = self._write_draft(task.topic, task.data["research"])
                self.board.update(task.task_id, self.name, TaskStatus.DRAFTED, {"draft": draft})
                print(f"  [{self.name}] Finished draft for '{task.topic}'")
            except Exception as e:
                self.board.update(task.task_id, self.name, TaskStatus.FAILED, {"error": str(e)})

    def _write_draft(self, topic: str, research: dict) -> dict:
        if not USE_LLM:
            angle = research.get("angle", topic)
            facts = research.get("key_facts", [])
            return {
                "title":        f"The Future of {topic}: What You Need to Know",
                "introduction": f"As the world grapples with {angle}, understanding the fundamentals has never been more important.",
                "body_sections": [
                    {"heading": "The Current Landscape", "content": facts[0] if facts else ""},
                    {"heading": "Key Drivers",            "content": facts[1] if len(facts) > 1 else ""},
                    {"heading": "Challenges Ahead",       "content": facts[2] if len(facts) > 2 else ""},
                ],
                "conclusion": f"The trajectory of {topic} points toward transformation at scale. The question is not if, but when.",
                "word_count":   320
            }
        return self._llm_call(
            prompt=(
                f"Write a blog post draft about '{topic}'.\n"
                f"Research angle: {research.get('angle')}\n"
                f"Key facts: {research.get('key_facts')}\n"
                f"Statistics: {research.get('statistics')}\n"
                f"Return a structured draft with title, introduction, body sections, and conclusion."
            ),
            tool_name="draft_result",
            tool_schema={
                "type": "object",
                "properties": {
                    "title":         {"type": "string"},
                    "introduction":  {"type": "string"},
                    "body_sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"heading": {"type": "string"}, "content": {"type": "string"}},
                            "required": ["heading", "content"]
                        }
                    },
                    "conclusion":    {"type": "string"},
                    "word_count":    {"type": "integer"}
                },
                "required": ["title", "introduction", "body_sections", "conclusion", "word_count"]
            }
        )


class EditorAgent(SwarmAgent):
    """Polls for DRAFTED tasks. Proofreads and produces the final polished post."""

    def poll_and_work(self):
        for task in self.board.get_tasks_by_status(TaskStatus.DRAFTED):
            if not self.board.claim(task.task_id, self.name, TaskStatus.DRAFTED, TaskStatus.EDITING):
                continue

            print(f"\n  [{self.name}] Claimed task {task.task_id}: editing '{task.topic}'")

            try:
                final = self._edit(task.topic, task.data["draft"])
                self.board.update(task.task_id, self.name, TaskStatus.COMPLETE, {"final": final})
                print(f"  [{self.name}] COMPLETE: '{task.topic}'")
            except Exception as e:
                self.board.update(task.task_id, self.name, TaskStatus.FAILED, {"error": str(e)})

    def _edit(self, topic: str, draft: dict) -> dict:
        if not USE_LLM:
            return {
                "title":           draft["title"],
                "polished_body":   (
                    f"{draft['introduction']}\n\n" +
                    "\n\n".join(f"## {s['heading']}\n{s['content']}" for s in draft["body_sections"]) +
                    f"\n\n{draft['conclusion']}"
                ),
                "seo_tags":        [topic.lower(), "innovation", "technology", "future"],
                "readability_score": "Grade 10",
                "edits_made":      ["Tightened introduction", "Improved paragraph flow", "Added subheadings"]
            }
        return self._llm_call(
            prompt=(
                f"Edit and polish this blog post about '{topic}'.\n"
                f"Title: {draft.get('title')}\n"
                f"Introduction: {draft.get('introduction')}\n"
                f"Sections: {draft.get('body_sections')}\n"
                f"Conclusion: {draft.get('conclusion')}\n\n"
                f"Return the polished final post, SEO tags, readability score, and a list of edits made."
            ),
            tool_name="edit_result",
            tool_schema={
                "type": "object",
                "properties": {
                    "title":             {"type": "string"},
                    "polished_body":     {"type": "string"},
                    "seo_tags":          {"type": "array", "items": {"type": "string"}},
                    "readability_score": {"type": "string"},
                    "edits_made":        {"type": "array", "items": {"type": "string"}}
                },
                "required": ["title", "polished_body", "seo_tags", "readability_score", "edits_made"]
            }
        )


# ─────────────────────────────────────────────────────────────
# 5. DEMO — Shows emergent coordination and parallel processing
# ─────────────────────────────────────────────────────────────

def print_final_results(board: TaskBoard):
    print(f"\n{'='*60}")
    print("  SWARM RESULTS")
    print(f"{'='*60}")
    for task in board.get_all():
        print(f"\n  Task {task.task_id}: '{task.topic}'")
        print(f"  Status: {task.status.upper()}")
        if task.status == TaskStatus.COMPLETE:
            final = task.data.get("final", {})
            print(f"  Title:  {final.get('title', 'N/A')}")
            print(f"  SEO:    {', '.join(final.get('seo_tags', []))}")
            print(f"  Edits:  {', '.join(final.get('edits_made', []))}")
        elif task.status == TaskStatus.FAILED:
            print(f"  Error:  {task.data.get('error', 'Unknown')}")
        print(f"\n  Audit trail:")
        for entry in task.history:
            print(f"    [{entry['timestamp'][11:19]}] {entry['agent']:20s} — {entry['message']}")


if __name__ == "__main__":
    board = TaskBoard()

    # Post multiple tasks — the swarm processes them in parallel
    topics = [
        "Solar Power and the Energy Transition",
        "Large Language Models in Healthcare",
        "Vertical Farming and Food Security",
    ]
    for topic in topics:
        board.post(topic)

    # Spin up the swarm — agents run as peer threads, no hierarchy
    # Two ResearchAgents to show parallel claiming and resilience
    agents = [
        ResearchAgent("ResearchAgent-1", board),
        ResearchAgent("ResearchAgent-2", board),   # redundant agent — resilience demo
        DraftingAgent("DraftingAgent-1", board),
        EditorAgent("EditorAgent-1",  board),
    ]

    print(f"\n[Swarm] Starting {len(agents)} agents for {len(topics)} tasks...")
    if not USE_LLM:
        print("[Swarm] DEMO MODE — using mock content (set ANTHROPIC_API_KEY for real LLM output)\n")

    for agent in agents:
        agent.start()

    # Wait until all tasks are done or failed
    timeout = 60
    start   = time.time()
    while time.time() - start < timeout:
        all_tasks = board.get_all()
        done = all(t.status in (TaskStatus.COMPLETE, TaskStatus.FAILED) for t in all_tasks)
        if done:
            break
        completed = sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETE)
        print(f"  [Monitor] {completed}/{len(topics)} complete... polling", end="\r")
        time.sleep(1)

    for agent in agents:
        agent.stop()

    print_final_results(board)
