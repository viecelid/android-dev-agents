# state.py

from pydantic import BaseModel, field_validator
from typing import Literal
from langgraph.graph import MessagesState


# ============================================================
# 📦 Datenmodelle
# ============================================================

class WorkflowTask(BaseModel):
    """Ein einzelner Task im Agenten-Workflow."""
    id: str
    title: str
    description: str
    priority: Literal["high", "medium", "low"]
    status: Literal["Todo", "In Progress", "Review", "Done"] = "Todo"
    branch_name: str | None = None
    files_affected: list[str] = []
    issue_data: dict = {}

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v):
        return v.lower() if isinstance(v, str) else v

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v):
        if isinstance(v, str):
            mapping = {
                "todo": "Todo",
                "in progress": "In Progress",
                "in_progress": "In Progress",
                "review": "Review",
                "done": "Done",
            }
            return mapping.get(v.lower(), v)
        return v


class PlannerDecision(BaseModel):
    """Eine strategische Entscheidung vom Planner."""
    component: str
    decision: str
    rationale: str
    target_files: list[str] = []


# ============================================================
# 📦 Zentraler Agent State
# ============================================================

class AgentState(MessagesState):
    """Zentraler State der durch den ganzen Graph fliesst."""

    # ── Projekt (einzelnes Repo) ──
    files: list[str] = []
    code_contents: str = ""
    project_analysis: str = ""
    project_initialized: bool = False

    # ── Human-Anweisung ──
    human_instruction: str = ""

    # ── Planung ──
    tasks: list[WorkflowTask] = []
    current_task: WorkflowTask | None = None
    planner_hints: str = ""

    # ── Planner-Entscheidungen ──
    planner_decisions: list[PlannerDecision] = []

    # ── Entwicklung ──
    generated_code: dict[str, str] = {}
    current_branch: str = ""
    written_files: list[str] = []

    # ── Testing ──
    test_results: str = ""
    build_success: bool = False
    retry_count: int = 0

    # ── Human Feedback ──
    human_feedback: str = ""
    feedback_target: str = ""

    # ── Tracking ──
    completed_tasks: list[dict] = []

    # ── Control ──
    phase: Literal[
        # Planner
        "plan",
        "review_plan",
        "review_plan_approved",
        "review_plan_rejected",

        # Developer
        "develop",
        "develop_retry",
        "review_dev",
        "review_dev_approved",
        "review_dev_rejected",

        # Tester
        "test",
        "review_pr",
        "review_pr_approved",
        "review_pr_rejected",

        # Abschluss
        "committed",
        "done",
    ] = "plan"
