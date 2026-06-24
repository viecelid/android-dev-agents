# agents/planner.py

import os
import time
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from pydantic import BaseModel, field_validator
from config.settings import settings
from state import WorkflowTask, PlannerDecision
from tools.github_tools import create_task_workflow


# ============================================================
# 🤖 LLM & Prompt Setup
# ============================================================

llm = ChatOpenAI(model=settings.default_model, temperature=0)

_prompt_path = os.path.join(settings.prompts_dir, "planner_prompt.md")
_system_prompt = open(_prompt_path, encoding="utf-8").read()
_system_prompt = _system_prompt.replace("{", "{{").replace("}", "}}")

planner_prompt = ChatPromptTemplate.from_messages([
    ("system", _system_prompt),
    ("human", "{context}"),
])


# ============================================================
# 📦 Strukturierte Outputs
# ============================================================

class PlannedDecision(BaseModel):
    """Eine strategische Entscheidung vom Planner."""
    component: str
    decision: str
    rationale: str
    target_files: list[str] = []


class PlannedTask(BaseModel):
    """Ein einzelner Task vom Planner."""
    id: str
    title: str
    description: str
    priority: str
    files_affected: list[str]
    implementation_hints: str
    decisions: list[PlannedDecision] = []
    target_file_structure: dict[str, str] = {}

    @field_validator("implementation_hints", mode="before")
    @classmethod
    def hints_to_string(cls, v):
        if isinstance(v, list):
            return "\n".join(str(item) for item in v)
        if v is None:
            return ""
        return v

    @field_validator("description", mode="before")
    @classmethod
    def description_to_string(cls, v):
        if isinstance(v, list):
            return "\n".join(str(item) for item in v)
        if v is None:
            return ""
        return v


class PlannerOutput(BaseModel):
    """Strukturierter Output – ein oder mehrere Tasks."""
    analysis: str
    tasks: list[PlannedTask]
    remaining_plan_summary: str = ""
    total_estimated_tasks: int = 1
    plan_adjustments: str = ""

    @field_validator("analysis", "remaining_plan_summary", "plan_adjustments", mode="before")
    @classmethod
    def ensure_string(cls, v):
        if isinstance(v, list):
            return "\n".join(str(item) for item in v)
        if v is None:
            return ""
        return v

    @field_validator("total_estimated_tasks", mode="before")
    @classmethod
    def ensure_int(cls, v):
        if v is None:
            return 1
        return v

    @field_validator("tasks", mode="before")
    @classmethod
    def ensure_list(cls, v):
        """Falls LLM nur einen Task als Objekt zurückgibt → in Liste wrappen."""
        if isinstance(v, dict):
            return [v]
        return v


planner_chain = planner_prompt | llm.with_structured_output(PlannerOutput)


# ============================================================
# 📏 Hilfsfunktionen
# ============================================================

MAX_CONTEXT_CHARS = 120000
MAX_CODE_CONTENTS_CHARS = 60000


def _truncate_context(context: str) -> str:
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n[... CONTEXT TRUNCATED ...]"
    return context


def _truncate_code_contents(code_contents: str) -> str:
    if len(code_contents) > MAX_CODE_CONTENTS_CHARS:
        code_contents = (
            code_contents[:MAX_CODE_CONTENTS_CHARS]
            + "\n\n[... CODE CONTENTS TRUNCATED ...]"
        )
    return code_contents


# ============================================================
# 🏗️ Planner Node – Hauptfunktion
# ============================================================

def run_planner(state: dict) -> dict:
    """
    🏗️ Planner Node:
    - Plant einen oder mehrere Tasks basierend auf der Human-Anweisung
    - Baut Kontext aus aktuellem Projekt-Stand + Anweisung
    - Erstellt NOCH KEINE GitHub-Ressourcen (erst nach Human OK)
    - Setzt den ERSTEN Task als current_task, Rest bleibt "Todo"
    """

    # ── State lesen ──
    feedback = state.get("human_feedback", "")
    human_instruction = state.get("human_instruction", "")
    current_task = state.get("current_task")
    completed = state.get("completed_tasks", [])
    tasks = state.get("tasks", [])
    files = state.get("files", [])
    project_initialized = state.get("project_initialized", False)

    code_contents = state.get("code_contents", "") or "Kein Code vorhanden."
    code_contents = _truncate_code_contents(code_contents)

    # ── Erkennen warum wir hier sind ──
    is_feedback_run = feedback and feedback.strip().lower() != "ok"
    is_continuation = len(completed) > 0 and not is_feedback_run

    # ── Noch offene Tasks aus vorheriger Planung? → nächsten starten ──
    if not is_feedback_run and tasks:
        remaining = [t for t in tasks if t.status == "Todo"]
        if remaining:
            next_task = remaining[0]
            print(f"\n  ➡️ Nächster Task aus Plan: {next_task.id} – {next_task.title}")
            _print_single_task_summary(next_task, len(completed) + 1, len(tasks))
            return {
                "messages": [
                    AIMessage(content=(
                        "🏗️ Nächster Task: " + next_task.id + " – " + next_task.title + "\n"
                        "⏸️ Warte auf Human Review..."
                    ))
                ],
                "current_task": next_task,
                "human_feedback": "",
                "feedback_target": "",
                "phase": "review_plan",
            }

    if is_feedback_run:
        print(f"\n  🔄 PLANNER RE-RUN: Human Feedback einarbeiten...")
    elif is_continuation:
        print(f"\n  🔄 PLANNER: {len(completed)} Tasks erledigt, plane nächsten...")
    else:
        print(f"\n  🆕 PLANNER: Neue Anweisung → Plan erstellen...")

    # ════════════════════════════════════════════════════════
    # 📝 Kontext aufbauen
    # ════════════════════════════════════════════════════════
    context_parts = []

    # 1️⃣ Human-Anweisung (DAS ZENTRALE ELEMENT)
    context_parts.append(
        "## 🎯 Aktuelle Anweisung vom Entwickler\n"
        + human_instruction + "\n"
    )

    # 2️⃣ Projekt-Status
    context_parts.append(
        "## 📊 Projekt-Status\n"
        "- **App:** " + settings.app_name + " (" + settings.app_package + ")\n"
        "- **Sprache:** " + settings.language + "\n"
        "- **Projekt initialisiert:** " + ("Ja" if project_initialized else "Nein") + "\n"
        "- **Dateien im Projekt:** " + str(len(files)) + "\n"
        "- **Erledigte Tasks (diese Session):** " + str(len(completed)) + "\n"
        "- **Min SDK:** " + str(settings.android_min_sdk) + "\n"
        "- **Target SDK:** " + str(settings.android_target_sdk) + "\n"
        "- **Compile SDK:** " + str(settings.android_compile_sdk) + "\n"
    )

    # 3️⃣ Projekt-Dateien
    if files:
        context_parts.append(
            "## 📂 Aktuelle Projekt-Dateien:\n"
            + "\n".join("- `" + f + "`" for f in files) + "\n"
        )

    # 4️⃣ Code-Inhalt
    context_parts.append(
        "## 📝 Aktueller Code-Inhalt:\n" + code_contents + "\n"
    )

    # 5️⃣ Erledigte Tasks
    if completed:
        completed_str = "\n".join(
            "- " + t.get("id", "?") + " – " + t.get("title", "?")
            + " (PR: " + t.get("pr_url", "?") + ")"
            for t in completed
        )
        context_parts.append(
            "## ✅ Bereits abgeschlossene Tasks (" + str(len(completed)) + "):\n"
            + completed_str + "\n"
        )

    # 6️⃣ Human Feedback (bei Rejection)
    if is_feedback_run:
        prev_task_info = "Kein vorheriger Task."
        if current_task:
            prev_task_info = (
                "- Task ID: " + current_task.id + "\n"
                "- Titel: " + current_task.title + "\n"
                "- Beschreibung: " + current_task.description + "\n"
                "- Dateien: " + ", ".join(current_task.files_affected)
            )
        context_parts.append(
            "## 📝 Human Feedback zum letzten Plan:\n" + feedback + "\n\n"
            "## Vorheriger Plan:\n" + prev_task_info + "\n"
        )

    # ── Context zusammenbauen ──
    context = "\n".join(context_parts)
    context = _truncate_context(context)

    # ════════════════════════════════════════════════════════
    # 🤖 LLM aufrufen (Structured Output) mit Retry
    # ════════════════════════════════════════════════════════
    print(f"  🤖 Rufe LLM auf (Context: {len(context)} chars)...")

    max_attempts = 3
    result = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = planner_chain.invoke({"context": context})
            break
        except Exception as e:
            print(f"  ⚠️ LLM-Aufruf fehlgeschlagen (Versuch {attempt}/{max_attempts}): {type(e).__name__}")
            if attempt == max_attempts:
                print(f"  ❌ Alle Versuche fehlgeschlagen: {e}")
                result = PlannerOutput(
                    analysis="Automatischer Fallback nach LLM-Fehler",
                    tasks=[PlannedTask(
                        id=f"TASK-{len(completed) + 1:03d}",
                        title=human_instruction[:80],
                        description=human_instruction,
                        priority="medium",
                        files_affected=[],
                        implementation_hints="Bitte manuell überprüfen – LLM-Parsing fehlgeschlagen.",
                    )],
                    remaining_plan_summary="",
                    total_estimated_tasks=1,
                )
            else:
                time.sleep(2)

    # ════════════════════════════════════════════════════════
    # 📋 Tasks erstellen
    # ════════════════════════════════════════════════════════
    planned_tasks = result.tasks
    all_workflow_tasks = []

    for i, planned in enumerate(planned_tasks):
        task_index = len(completed) + i + 1
        task_id = planned.id or f"TASK-{task_index:03d}"

        wf_task = WorkflowTask(
            id=task_id,
            title=planned.title,
            description=planned.description,
            priority=planned.priority,
            files_affected=planned.files_affected,
            status="Todo",
            branch_name=f"feature/{task_id}",
        )
        all_workflow_tasks.append(wf_task)

    # Erster Task wird current_task
    first_task = all_workflow_tasks[0]

    # ── Planner-Entscheidungen vom ersten Task konvertieren ──
    first_planned = planned_tasks[0]
    decisions = [
        PlannerDecision(
            component=d.component,
            decision=d.decision,
            rationale=d.rationale,
            target_files=d.target_files,
        )
        for d in first_planned.decisions
    ]

    # ── Console-Ausgabe ──
    _print_plan_summary(all_workflow_tasks, planned_tasks, result, decisions, is_feedback_run, completed)

    # ════════════════════════════════════════════════════════
    # 📦 State updaten
    # ════════════════════════════════════════════════════════
    return {
        "messages": [
            AIMessage(content=(
                "🏗️ Plan: " + str(len(all_workflow_tasks)) + " Task(s) geplant\n"
                "1️⃣ " + first_task.id + " – " + first_task.title + "\n"
                "⏸️ Warte auf Human Review..."
            ))
        ],
        "project_analysis": result.analysis,
        "tasks": all_workflow_tasks,
        "current_task": first_task,
        "planner_decisions": decisions,
        "planner_hints": first_planned.implementation_hints,
        "human_feedback": "",
        "feedback_target": "",
        "phase": "review_plan",
    }


# ============================================================
# 🖨️ Console Output
# ============================================================

def _print_plan_summary(all_tasks, planned_tasks, result, decisions, is_feedback, completed):
    print("\n" + "=" * 60)
    print("🏗️  PLANNER – Vorschlag (noch NICHT auf GitHub!)")
    print("=" * 60)

    if result.plan_adjustments:
        print(f"\n🔄 Plan-Anpassungen:\n   {result.plan_adjustments}")
    if is_feedback:
        print(f"\n📝 Feedback eingearbeitet: ✅")

    print(f"\n📊 Gesamtplan: {len(all_tasks)} Task(s)")
    print(f"   Bereits erledigt: {len(completed)}")

    for i, (task, planned) in enumerate(zip(all_tasks, planned_tasks)):
        marker = "➡️" if i == 0 else "  "
        print(f"\n{marker} Task {i + 1}/{len(all_tasks)}: {task.id} – {task.title}")
        print(f"   Priorität: {task.priority}")
        print(f"   Dateien: {', '.join(task.files_affected)}")
        print(f"   Beschreibung: {task.description[:150]}...")

        if i == 0:
            print(f"\n💡 Developer-Anweisungen:\n   {planned.implementation_hints}")

            if planned.decisions:
                print(f"\n🏛️  Planner-Entscheidungen:")
                for d in planned.decisions:
                    print(f"   - {d.component}: {d.decision}")
                    print(f"     Begründung: {d.rationale}")
                    if d.target_files:
                        print(f"     Dateien: {', '.join(d.target_files)}")

            if planned.target_file_structure:
                print(f"\n📂 Ziel-Dateistruktur:")
                for path, desc in planned.target_file_structure.items():
                    print(f"   - {path} → {desc}")

    if result.remaining_plan_summary:
        print(f"\n🔮 Restlicher Plan:\n   {result.remaining_plan_summary}")

    print(f"\n⏸️  Branch + Issue werden erst nach deinem OK erstellt!")
    print(f"   Erster Task: {all_tasks[0].id} – {all_tasks[0].title}")
    print("=" * 60)


def _print_single_task_summary(task, task_index, total):
    """Zeigt einen einzelnen Task aus dem bestehenden Plan."""
    print("\n" + "=" * 60)
    print(f"🏗️  NÄCHSTER TASK ({task_index}/{total})")
    print("=" * 60)
    print(f"\n📋 {task.id} – {task.title}")
    print(f"   Priorität: {task.priority}")
    print(f"   Dateien: {', '.join(task.files_affected)}")
    print(f"   Beschreibung: {task.description[:200]}")
    print(f"\n⏸️  Branch + Issue werden erst nach deinem OK erstellt!")
    print("=" * 60)


# ============================================================
# ✅ Post-Approval Handler
# ============================================================

def run_planner_approved(state: dict) -> dict:
    """Nach Human OK: GitHub Branch + Issue erstellen."""
    task = state.get("current_task")

    if not task:
        return {
            "messages": [AIMessage(content="⚠️ Kein Task für Approval")],
            "phase": "develop",
        }

    decisions = state.get("planner_decisions", [])
    hints = state.get("planner_hints", "")

    print("\n" + "=" * 60)
    print("✅  PLAN APPROVED – Erstelle GitHub Branch + Issue")
    print("=" * 60)

    # ── Issue Body bauen ──
    task_body = "## " + task.title + "\n\n**Priorität:** " + task.priority + "\n\n"

    if decisions:
        task_body += (
            "**Architektur-Entscheidungen:**\n"
            + "\n".join(
                "- **" + d.component + "**: " + d.decision + " – " + d.rationale
                for d in decisions
            )
            + "\n\n"
        )

    task_body += (
        "**Betroffene Dateien:**\n"
        + "\n".join("- `" + f + "`" for f in task.files_affected)
        + "\n\n"
        "---\n\n" + task.description + "\n\n"
        "**Implementierungs-Hinweise:**\n" + hints
    )

    # ── GitHub Workflow ──
    print(f"  🐙 Erstelle GitHub Branch + Issue für {task.id}...")
    workflow_result = create_task_workflow(
        task_id=task.id,
        task_title=task.title,
        task_body=task_body,
    )

    # ── Task aktualisieren ──
    task.branch_name = workflow_result["branch_name"]
    task.issue_data = workflow_result.get("issue_data", {})
    task.status = "In Progress"

    # ── Tasks-Liste aktualisieren ──
    tasks = state.get("tasks", [])
    updated_tasks = list(tasks)
    existing_idx = next(
        (i for i, t in enumerate(updated_tasks) if t.id == task.id),
        None,
    )
    if existing_idx is not None:
        updated_tasks[existing_idx] = task

    print(f"  📋 Task: {task.id} – {task.title}")
    print(f"  🌿 Branch: {task.branch_name}")
    print(f"  📋 Issue: {task.issue_data.get('issue_url', '?')}")
    print(f"  ➡️  Weiter zum Developer...")
    print("=" * 60)

    return {
        "messages": [
            AIMessage(content=(
                "✅ Plan approved: " + task.id + " – " + task.title + "\n"
                "🌿 Branch: " + task.branch_name + "\n"
                "💻 Weiter zum Developer..."
            ))
        ],
        "current_task": task,
        "current_branch": task.branch_name,
        "tasks": updated_tasks,
        "phase": "develop",
    }


# ============================================================
# ❌ Post-Rejection Handler
# ============================================================

def run_planner_rejected(state: dict) -> dict:
    """Nach Human NICHT OK: Zurück zum Planner mit Feedback."""
    task = state.get("current_task")
    feedback = state.get("human_feedback", "")

    print("\n" + "=" * 60)
    print("❌  PLAN REJECTED – Feedback-Loop")
    print("=" * 60)
    print(f"  📋 Task: {task.title if task else 'N/A'}")
    print(f"  📝 Feedback: {feedback[:120]}...")
    print("=" * 60)

    return {
        "messages": [
            AIMessage(content=(
                "❌ Plan rejected: " + (task.id if task else "N/A") + "\n"
                "📝 Feedback: " + feedback[:200] + "\n"
                "🔄 Planner überarbeitet..."
            ))
        ],
        "phase": "review_plan_rejected",
    }
