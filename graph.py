# graph.py

import sqlite3
from pathlib import Path
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import AIMessage
from state import AgentState, WorkflowTask
from agents.planner import (
    run_planner,
    run_planner_approved,
    run_planner_rejected,
)
from agents.developer import (
    run_developer,
    run_developer_approved,
    run_developer_rejected,
)
from agents.tester import run_tester
from tools.github_tools import (
    commit_and_push,
    create_pull_request,
    set_project_item_status,
    close_issue,
)
from config.settings import settings


# ============================================================
# ⚙️ Konstanten
# ============================================================

MAX_RETRIES = settings.max_retries


# ============================================================
# 💾 Checkpointing (SQLite)
# ============================================================

checkpoint_dir = Path("checkpoints")
checkpoint_dir.mkdir(exist_ok=True)

conn = sqlite3.connect(
    str(checkpoint_dir / "workflow.db"),
    check_same_thread=False,
)
checkpointer = SqliteSaver(conn)


# ============================================================
# 🏗️ Planner Node
# ============================================================

def planner_node(state: dict) -> dict:
    """
    🏗️ Planner Node – plant Tasks basierend auf der Human-Anweisung.

    Phasen:
      - "plan"                  → Neue Anweisung → Plan erstellen
      - "review_plan_approved"  → Human hat OK gegeben → Task starten
      - "review_plan_rejected"  → Human hat Feedback → Plan überarbeiten
    """
    phase = state.get("phase", "plan")
    current_task = state.get("current_task")
    tasks = state.get("tasks", [])

    # ── Task abgeschlossen → Done (zurück zur main.py Loop) ──
    # NUR wenn es bereits Tasks in DIESEM Durchlauf gab (tasks nicht leer)
    # UND kein aktueller Task mehr offen ist
    if phase == "plan" and current_task is None and tasks:
        remaining = [t for t in tasks if t.status == "Todo"]

        if not remaining:
            completed = state.get("completed_tasks", [])
            print("\n" + "=" * 60)
            print("🎉 ANWEISUNG ABGESCHLOSSEN!")
            print(f"   {len(completed)} Tasks erfolgreich erledigt.")
            print("=" * 60)
            return {
                "messages": [AIMessage(content=(
                    "🎉 Anweisung abgeschlossen!\n"
                    "📊 " + str(len(completed)) + " Tasks erledigt."
                ))],
                "phase": "done",
            }

    # ── Phase-basiertes Routing ──
    if phase == "review_plan_approved":
        return run_planner_approved(state)
    elif phase == "review_plan_rejected":
        return run_planner(state)
    else:
        return run_planner(state)


# ============================================================
# 💻 Developer Node
# ============================================================

def developer_node(state: dict) -> dict:
    """
    💻 Developer Node – implementiert den aktuellen Task.

    Phasen:
      - "develop"              → Erster Durchlauf
      - "develop_retry"        → Retry nach Build-Fehler
      - "review_dev_approved"  → Human hat OK gegeben → Tester
      - "review_dev_rejected"  → Human hat Feedback → überarbeiten
    """
    phase = state.get("phase", "develop")
    retry_count = state.get("retry_count", 0)

    if phase == "review_dev_approved":
        return run_developer_approved(state)

    elif phase == "review_dev_rejected":
        return run_developer(state)

    elif phase == "develop_retry":
        new_count = retry_count + 1
        print(f"  🔄 Build-Retry {new_count}/{MAX_RETRIES}")
        result = run_developer(state)
        result["retry_count"] = new_count
        return result

    else:
        # Erster Durchlauf: Counter reset
        result = run_developer(state)
        result["retry_count"] = 0
        return result


# ============================================================
# 🧪 Tester Node
# ============================================================

def tester_node(state: dict) -> dict:
    """
    🧪 Tester Node – führt Build aus und analysiert Ergebnis.
    Setzt phase auf "review_pr" (PASS) oder "develop_retry" (FAIL).
    """
    return run_tester(state)


# ============================================================
# 👤 Human Review Node
# ============================================================

def _normalize_input(raw: str) -> str:
    """Normalisiert Terminal-Input – entfernt unsichtbare Zeichen."""
    cleaned = raw.strip()
    cleaned = "".join(c for c in cleaned if c.isprintable() or c == " ")
    cleaned = cleaned.strip()
    return cleaned


def human_review(state: dict) -> dict:
    """
    👤 Human Review – wartet auf Terminal-Input.
    Erkennt automatisch welche Phase gerade reviewed wird.
    """
    phase = state.get("phase", "")
    task = state.get("current_task")
    retry_count = state.get("retry_count", 0)
    task_id = task.id if task else "N/A"
    task_title = task.title if task else "N/A"

    # ── Console Header ──
    if phase == "review_plan":
        print(f"\n👤 Review: Plan ({task_id})")
    elif phase == "review_dev":
        print(f"\n👤 Review: Code ({task_id})")
    elif phase == "review_pr":
        print(f"\n👤 Review: Test-Ergebnis / PR ({task_id})")
    elif phase == "develop_retry":
        print(f"\n👤 Review: Build-Fehler ({task_id})")

    # ── Zeige Retry-Info wenn Max erreicht ──
    if phase == "develop_retry" and retry_count >= MAX_RETRIES:
        print(f"\n  ❌ Max Retries ({MAX_RETRIES}) erreicht!")
        print(f"  📋 Task: {task_title}")
        print(f"  📋 Build-Fehler konnten nicht automatisch behoben werden.")
        print(f"  💡 Optionen:")
        print(f"     - Feedback eingeben → Manueller Hinweis an Developer")
        print(f"     - 'skip' → Task überspringen")
        print(f"     - 'ok' → Trotzdem weiter zum PR Review")

    # ── Input holen ──
    print(f"\n{'─' * 40}")
    raw_input = input("👤 Dein Review (ok / Feedback): ")
    feedback = _normalize_input(raw_input)
    print(f"{'─' * 40}")
    print(f"  [Input erkannt: '{feedback}']")

    # ── Skip → Task überspringen ──
    if feedback.lower() in ("skip", "überspringen", "next"):
        print(f"  ⏭️ Task {task_id} übersprungen")
        return {
            "human_feedback": "",
            "feedback_target": "",
            "retry_count": 0,
            "current_task": None,
            "generated_code": {},
            "written_files": [],
            "test_results": "",
            "build_success": False,
            "current_branch": "",
            "phase": "plan",
        }

    # ── "ok" → Approved ──
    if feedback.lower() in ("ok", "yes", "y", "ja", "j", "lgtm", ""):
        if phase == "review_plan":
            print(f"  ✅ Plan freigegeben ({task_id})")
            return {
                "human_feedback": "",
                "feedback_target": "",
                "phase": "review_plan_approved",
            }
        elif phase == "review_dev":
            print(f"  ✅ Code freigegeben ({task_id})")
            return {
                "human_feedback": "",
                "feedback_target": "",
                "phase": "review_dev_approved",
            }
        elif phase == "review_pr":
            print(f"  ✅ PR freigegeben → Commit ({task_id})")
            return {
                "human_feedback": "",
                "feedback_target": "",
                "phase": "review_pr_approved",
            }
        elif phase == "develop_retry":
            print(f"  ✅ Trotzdem weiter zum PR ({task_id})")
            return {
                "human_feedback": "",
                "feedback_target": "",
                "phase": "review_pr_approved",
            }
        else:
            return {
                "human_feedback": "",
                "feedback_target": "",
                "phase": phase + "_approved",
            }

    # ── Feedback → Rejected / Retry mit Hint ──
    if phase == "review_plan":
        print(f"  📝 Feedback an Planner ({task_id})")
        return {
            "human_feedback": feedback,
            "feedback_target": "planner",
            "phase": "review_plan_rejected",
        }
    elif phase == "review_dev":
        print(f"  📝 Feedback an Developer ({task_id})")
        return {
            "human_feedback": feedback,
            "feedback_target": "developer",
            "phase": "review_dev_rejected",
        }
    elif phase == "review_pr":
        print(f"  📝 Feedback an Developer ({task_id})")
        return {
            "human_feedback": feedback,
            "feedback_target": "developer",
            "phase": "review_pr_rejected",
        }
    elif phase == "develop_retry":
        print(f"  📝 Manueller Hinweis an Developer → Counter reset ({task_id})")
        return {
            "human_feedback": feedback,
            "feedback_target": "developer",
            "retry_count": 0,
            "phase": "develop_retry",
        }
    else:
        return {
            "human_feedback": feedback,
            "feedback_target": phase,
            "phase": phase + "_rejected",
        }


# ============================================================
# 📦 Commit & PR Node
# ============================================================

def _run_commit(state: dict) -> dict:
    """
    📦 Commit Node – committed Code und erstellt PR.
    """
    task = state.get("current_task")
    if not task:
        return {
            "messages": [AIMessage(content="⚠️ Kein Task zum Committen")],
            "phase": "plan",
        }

    branch = state.get("current_branch", "")
    written_files = state.get("written_files", [])
    generated_code = state.get("generated_code", {})

    print("\n" + "=" * 60)
    print("📦  COMMIT & PR")
    print("=" * 60)

    # ── Commit & Push ──
    all_files = list(set(written_files + list(generated_code.keys())))

    push_result = commit_and_push(
        files=all_files,
        message="feat(" + task.id + "): " + task.title,
        branch_name=branch,
    )

    # ── Pull Request erstellen (nur wenn Commits vorhanden) ──
    if push_result == "nothing to commit":
        print(f"  ⚠️ Keine Änderungen – PR wird übersprungen")
        pr_url = "n/a (keine Änderungen)"
    else:
        issue_number = None
        if hasattr(task, "issue_data") and task.issue_data:
            issue_number = task.issue_data.get("number")

        files_list = "\n".join("- `" + f + "`" for f in all_files)

        pr_url = create_pull_request(
            branch=branch,
            title=task.id + ": " + task.title,
            body=(
                "## " + task.title + "\n\n"
                + task.description + "\n\n"
                "### Geänderte Dateien (" + str(len(all_files)) + ")\n"
                + files_list
            ),
            issue_number=issue_number,
        )

    # ── GitHub Project Status → Done ──
    if hasattr(task, "issue_data") and task.issue_data:
        item_id = task.issue_data.get("project_item_id")
        if item_id:
            set_project_item_status(item_id, "Done")

    # ── Issue schliessen ──
    issue_number = None
    if hasattr(task, "issue_data") and task.issue_data:
        issue_number = task.issue_data.get("number")
    if issue_number:
        close_issue(issue_number)

    # ── Task als erledigt markieren ──
    completed = list(state.get("completed_tasks", []))
    completed.append({
        "id": task.id,
        "title": task.title,
        "branch": branch,
        "pr_url": pr_url,
        "files": all_files,
    })

    print(f"\n  📋 Task: {task.id} – {task.title}")
    print(f"  🌿 Branch: {branch}")
    print(f"  🔀 PR: {pr_url}")
    print(f"  📊 Total erledigt: {len(completed)}")
    print("=" * 60)

    return {
        "messages": [AIMessage(content=(
            "📦 **" + task.id + ": Committed & PR erstellt**\n"
            "🔀 PR: " + pr_url + "\n"
            "📊 Total erledigt: " + str(len(completed))
        ))],
        "completed_tasks": completed,
        "current_task": None,
        "generated_code": {},
        "written_files": [],
        "test_results": "",
        "build_success": False,
        "retry_count": 0,
        "current_branch": "",
        "phase": "plan",
    }


# ============================================================
# 🔀 Routing-Funktionen
# ============================================================

def route_after_planner(state: dict) -> str:
    """Route nach Planner: Review, Developer oder Done."""
    phase = state.get("phase", "")
    if phase == "done":
        return END
    elif phase == "review_plan":
        return "human_review"
    elif phase == "develop":
        return "developer"
    else:
        return "human_review"


def route_after_human_review(state: dict) -> str:
    """Route nach Human Review."""
    phase = state.get("phase", "")

    # Plan Review
    if phase == "review_plan_approved":
        return "planner"
    elif phase == "review_plan_rejected":
        return "planner"

    # Developer Review
    elif phase == "review_dev_approved":
        return "developer"
    elif phase == "review_dev_rejected":
        return "developer"

    # PR/Test Review
    elif phase == "review_pr_approved":
        return "commit"
    elif phase == "review_pr_rejected":
        return "developer"

    # Max Retries → Human gibt Feedback → nochmal Developer
    elif phase == "develop_retry":
        return "developer"

    # Skip → zurück zum Planner
    elif phase == "plan":
        return "planner"

    else:
        return "planner"


def route_after_developer(state: dict) -> str:
    """Route nach Developer: Human Review oder Tester."""
    phase = state.get("phase", "")
    if phase == "review_dev":
        return "human_review"
    elif phase == "test":
        return "tester"
    else:
        return "human_review"


def route_after_tester(state: dict) -> str:
    """Route nach Tester: PR Review oder Retry."""
    phase = state.get("phase", "")
    retry_count = state.get("retry_count", 0)

    if phase == "review_pr":
        return "human_review"
    elif phase == "develop_retry":
        if retry_count >= MAX_RETRIES:
            print(f"\n  ❌ Max Retries ({MAX_RETRIES}) erreicht → Human Review")
            return "human_review"
        print(f"\n  🔄 Retry {retry_count}/{MAX_RETRIES} → zurück zum Developer")
        return "developer"
    else:
        return "human_review"


# ============================================================
# 🔀 Graph Definition
# ============================================================

workflow = StateGraph(AgentState)

# ── Nodes ──
workflow.add_node("planner", planner_node)
workflow.add_node("developer", developer_node)
workflow.add_node("tester", tester_node)
workflow.add_node("human_review", human_review)
workflow.add_node("commit", _run_commit)

# ── Entry Point ──
workflow.set_entry_point("planner")

# ── Conditional Edges ──
workflow.add_conditional_edges("planner", route_after_planner)
workflow.add_conditional_edges("human_review", route_after_human_review)
workflow.add_conditional_edges("developer", route_after_developer)
workflow.add_conditional_edges("tester", route_after_tester)

# ── Commit → zurück zum Planner ──
workflow.add_edge("commit", "planner")

# ── Graph kompilieren ──
app = workflow.compile(checkpointer=checkpointer)
