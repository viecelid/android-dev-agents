# agents/developer.py

import os
import re
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from config.settings import settings
from tools.file_tools import (
    read_file,
    write_generated_code,
    read_file_tool,
    list_files_tool,
    list_dir_tool,
)
from tools.github_tools import (
    set_project_item_status,
    add_issue_comment,
    checkout_branch,
)


# ============================================================
# 🤖 LLM & Prompt Setup
# ============================================================

llm = ChatOpenAI(model=settings.default_model, temperature=0)

_prompt_path = os.path.join(settings.prompts_dir, "developer_prompt.md")
_system_prompt = open(_prompt_path, encoding="utf-8").read()
_system_prompt = _system_prompt.replace("{", "{{").replace("}", "}}")

# Developer-Tools (ein Repo – lesen + navigieren)
developer_tools = [
    read_file_tool,
    list_files_tool,
    list_dir_tool,
]

# LLM mit Tools
llm_with_tools = llm.bind_tools(developer_tools)

developer_prompt = ChatPromptTemplate.from_messages([
    ("system", _system_prompt),
    ("human", "{context}"),
])


# ============================================================
# 📏 Konstanten
# ============================================================

MAX_FILE_CHARS = 5000
MAX_CONTEXT_CHARS = 120000
MAX_AGENT_ITERATIONS = 10


# ============================================================
# 📏 Hilfsfunktionen
# ============================================================

def _truncate_context(context: str) -> str:
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n[... CONTEXT TRUNCATED ...]"
    return context


# ============================================================
# 🔧 GitHub Helpers
# ============================================================

def _get_project_item_id(task) -> str | None:
    if hasattr(task, "issue_data") and task.issue_data:
        return task.issue_data.get("project_item_id")
    return None


def _get_issue_number(task) -> int | None:
    if hasattr(task, "issue_data") and task.issue_data:
        return task.issue_data.get("number")
    return None


def _update_github_status(task, status: str):
    item_id = _get_project_item_id(task)
    if item_id:
        set_project_item_status(item_id, status)


def _add_dev_comment(task, comment_body: str):
    issue_number = _get_issue_number(task)
    if issue_number:
        add_issue_comment(issue_number, comment_body)


# ============================================================
# 🔍 Parser: Generierte Dateien
# ============================================================

def _parse_generated_code(llm_content: str) -> dict[str, str]:
    """Parst ### DATEI: Blöcke aus dem LLM-Output."""
    files = {}
    pattern = r"### DATEI:\s*(.+?)\n```\w*\n(.*?)```"
    matches = re.findall(pattern, llm_content, re.DOTALL)

    # Erlaubte Datei-Extensions
    allowed_extensions = (
        ".kt", ".java", ".xml", ".kts", ".toml",
        ".properties", ".gradle", ".md", ".json",
    )

    for filepath, code in matches:
        filepath = filepath.strip().lstrip("./").replace("//", "/")

        if len(filepath) > 300 or "\n" in filepath:
            continue

        if filepath.endswith(allowed_extensions):
            files[filepath] = code.strip()

    if files:
        print(f"  📦 {len(files)} Dateien geparst:")
        for f in files:
            print(f"     • {f}")
    else:
        print(f"  ⚠️ Keine Dateien aus LLM-Output geparst")

    return files


# ============================================================
# 🔧 Tool-Map
# ============================================================

TOOL_MAP = {
    "read_file_tool": read_file_tool,
    "list_files_tool": list_files_tool,
    "list_dir_tool": list_dir_tool,
}


# ============================================================
# 🔧 Tool-Calls ausführen
# ============================================================

def _execute_tool_calls(response) -> list[dict]:
    """
    Führt Tool-Calls aus dem LLM-Response aus.
    Returns: tool_messages
    """
    tool_messages = []

    if not hasattr(response, "tool_calls") or not response.tool_calls:
        return tool_messages

    for tool_call in response.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call.get("id", "")

        print(f"  🔧 Tool: {tool_name}({tool_args})")

        tool_fn = TOOL_MAP.get(tool_name)
        if tool_fn:
            try:
                result = tool_fn.invoke(tool_args)
            except Exception as e:
                result = f"⚠️ Tool-Fehler: {e}"
                print(f"     ❌ {result}")

            result_str = str(result)
            print(f"     → {result_str[:200]}")

            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": result_str,
            })
        else:
            print(f"     ⚠️ Unbekanntes Tool: {tool_name}")
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": f"⚠️ Unbekanntes Tool: {tool_name}",
            })

    return tool_messages


# ============================================================
# 🔄 Agent Loop (Tools + Code Generation)
# ============================================================

def _run_agent_loop(context: str) -> str:
    """
    Führt den Developer als Agent mit Tool-Zugriff aus.
    Der LLM kann Tools aufrufen UND Code generieren.

    Returns: final_content
    """
    messages = [
        {"role": "system", "content": _system_prompt},
        {"role": "user", "content": context},
    ]

    final_content = ""

    for i in range(MAX_AGENT_ITERATIONS):
        response = llm_with_tools.invoke(messages)

        # Content sammeln
        if response.content:
            final_content = response.content

        # Keine Tool-Calls → fertig
        if not hasattr(response, "tool_calls") or not response.tool_calls:
            print(f"  ✅ Agent fertig nach {i + 1} Iteration(en)")
            return final_content

        # Tool-Calls ausführen
        tool_messages = _execute_tool_calls(response)

        # Response + Tool-Results als Messages hinzufügen
        messages.append(response)
        messages.extend(tool_messages)

        print(f"  🔄 Agent Iteration {i + 1}: "
              f"{len(response.tool_calls)} Tool-Calls")

    # Max Iterations erreicht
    print(f"  ⚠️ Max Agent-Iterationen ({MAX_AGENT_ITERATIONS}) erreicht")
    print(f"  🤖 Finaler Call ohne Tools...")

    final_response = llm.invoke(messages)
    if final_response.content:
        final_content = final_response.content

    return final_content


# ============================================================
# 💻 Developer Node – Hauptfunktion
# ============================================================

def run_developer(state: dict) -> dict:
    """
    💻 Developer Node:
    - Bekommt Task + Planner-Vorgaben als Daten-Context
    - Kann Tools aufrufen (Dateien lesen, Verzeichnisse erkunden)
    - Generiert Code via ### DATEI: Pattern
    - Alle Anweisungen stehen im developer_prompt.md
    """
    task = state.get("current_task")

    if not task:
        return {
            "messages": [AIMessage(content="⚠️ Kein Task zum Entwickeln")],
            "phase": "test",
        }

    feedback = state.get("human_feedback", "")
    retry_count = state.get("retry_count", 0)
    test_results = state.get("test_results", "")
    generated_code = state.get("generated_code", {})
    branch = state.get("current_branch", "")
    planner_decisions = state.get("planner_decisions", [])
    planner_hints = state.get("planner_hints", "")

    is_feedback_run = feedback and feedback.strip().lower() != "ok"
    is_retry = retry_count > 0 and test_results

    # ── Console Header ──
    print("\n" + "=" * 60)
    print("💻  DEVELOPER")
    print("=" * 60)

    if is_retry:
        print(f"\n  🔄 Retry #{retry_count}: Fixing Build-Fehler...")
    elif is_feedback_run:
        print(f"\n  📝 Feedback einarbeiten...")
    else:
        print(f"\n  🆕 Erster Durchlauf für Task...")

    print(f"  📋 Task: {task.id} – {task.title}")
    print(f"  🌿 Branch: {branch}")

    # ── Branch auschecken ──
    if branch:
        checkout_branch(branch)

    # ════════════════════════════════════════════════════════
    # 📝 Context aufbauen
    # ════════════════════════════════════════════════════════
    context_parts = []

    # Task-Info
    context_parts.append(
        "## 📋 Aktueller Task\n"
        "- **ID:** " + task.id + "\n"
        "- **Titel:** " + task.title + "\n"
        "- **Beschreibung:** " + task.description + "\n"
        "- **Betroffene Dateien:** " + ", ".join(task.files_affected) + "\n"
    )

    # Planner-Anweisungen
    if planner_hints:
        context_parts.append(
            "## 💡 Developer-Anweisungen vom Planner:\n" + planner_hints + "\n"
        )

    # Planner-Entscheidungen
    if planner_decisions:
        dec_str = "\n".join(
            "- **" + d.component + ":** " + d.decision
            + "\n  Begründung: " + d.rationale
            + ("\n  Dateien: " + ", ".join(d.target_files) if d.target_files else "")
            for d in planner_decisions
        )
        context_parts.append(
            "## 🏛️ Architektur-Entscheidungen:\n" + dec_str + "\n"
        )

    # Betroffene Dateien vorab lesen (falls sie schon existieren)
    for filepath in task.files_affected:
        content = read_file(filepath)
        if content:
            truncated = content[:MAX_FILE_CHARS]
            if len(content) > MAX_FILE_CHARS:
                truncated += "\n// ... [TRUNCATED – use read_file_tool for full content]"
            ext = filepath.split(".")[-1] if "." in filepath else ""
            context_parts.append(
                "## 📖 Bestehende Datei: " + filepath + "\n```" + ext + "\n" + truncated + "\n```\n"
            )
            print(f"  📖 Datei gelesen: {filepath} ({len(content)} chars)")
        else:
            context_parts.append(
                "## 📖 Datei: " + filepath + "\n"
                "ℹ️ Datei existiert noch nicht – wird neu erstellt.\n"
            )

    # Bereits generierter Code (vorherige Durchläufe)
    if generated_code:
        existing_str = "\n".join(
            "- `" + f + "` (" + str(len(c)) + " chars)"
            for f, c in generated_code.items()
        )
        context_parts.append(
            "## 📂 Bereits generierte/geänderte Dateien:\n" + existing_str + "\n"
            "Nutze read_file_tool um den Inhalt einer Datei zu lesen.\n"
        )

    # Build-Fehler (bei Retry)
    if is_retry and test_results:
        context_parts.append(
            "## ❌ Build-Fehler (du musst das fixen!):\n"
            "```\n" + test_results[-3000:] + "\n```\n\n"
            "Fixe den Fehler im Code. "
            "Ändere NICHT die Gradle/Build-Konfiguration es sei denn der Fehler liegt dort!\n"
        )

    # Human Feedback
    if is_feedback_run:
        context_parts.append(
            "## 📝 Human Feedback (MUSS eingearbeitet werden):\n"
            + feedback + "\n"
        )

    # Verfügbare Tools
    context_parts.append(
        "## 🔧 Verfügbare Tools\n"
        "Du hast Zugriff auf diese Tools – nutze sie bei Bedarf:\n\n"
        "- `read_file_tool(filepath)` → Datei aus dem Projekt lesen\n"
        "- `list_files_tool(directory)` → Alle Dateien im Projekt listen\n"
        "- `list_dir_tool(directory)` → Verzeichnis-Inhalt listen\n\n"
        "**Wichtig:** Nutze die Tools um bestehenden Code zu verstehen "
        "bevor du Änderungen machst.\n"
    )

    context = "\n".join(context_parts)
    context = _truncate_context(context)

    # ════════════════════════════════════════════════════════
    # 🤖 Agent Loop (Tools + Code Generation)
    # ════════════════════════════════════════════════════════
    print(f"  🤖 Rufe LLM auf (Context: {len(context)} chars)...")

    llm_content = _run_agent_loop(context)

    # ════════════════════════════════════════════════════════
    # 📦 Code parsen und schreiben
    # ════════════════════════════════════════════════════════
    new_code = {}
    if llm_content:
        new_code = _parse_generated_code(llm_content)

    written_files = []
    if new_code:
        written_files = write_generated_code(new_code)

    # Code-Dict aktualisieren (für Tester-Context)
    updated_code = dict(generated_code)
    updated_code.update(new_code)

    total_files = len(written_files)

    # ════════════════════════════════════════════════════════
    # 💬 GitHub kommentieren
    # ════════════════════════════════════════════════════════
    _update_github_status(task, "In Progress")

    file_summary = "\n".join(
        "- `" + f + "`" for f in written_files
    )

    comment_type = "Code generiert"
    if is_retry:
        comment_type = "Build-Fix (Retry #" + str(retry_count) + ")"
    elif is_feedback_run:
        comment_type = "Feedback eingearbeitet"

    _add_dev_comment(task, (
        "## 💻 Developer – " + comment_type + "\n\n"
        "**Task:** " + task.title + "\n"
        "**Dateien (" + str(total_files) + "):**\n"
        + file_summary
    ))

    # ════════════════════════════════════════════════════════
    # 🖨️ Console-Ausgabe
    # ════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("💻  DEVELOPER – Implementation abgeschlossen")
    print("=" * 60)
    print(f"\n📋 Task: {task.id} – {task.title}")
    print(f"🌿 Branch: {branch}")
    print(f"\n📦 {total_files} Dateien geschrieben:")

    for f in written_files:
        if f in new_code:
            lines = new_code[f].count("\n") + 1
            print(f"   📄 {f} ({lines} Zeilen)")
        else:
            print(f"   📋 {f}")

    if not written_files:
        print(f"   ⚠️ Keine Dateien geschrieben!")
        if llm_content:
            print(f"   📝 LLM-Output (Auszug):")
            print(f"   {llm_content[:500]}")

    print("=" * 60)

    # ════════════════════════════════════════════════════════
    # 📦 State
    # ════════════════════════════════════════════════════════
    return {
        "messages": [
            AIMessage(content=(
                "💻 **" + task.id + ": " + comment_type + "**\n\n"
                "Dateien: " + str(total_files) + "\n"
                + file_summary + "\n\n"
                "⏸️ Warte auf Human Review..."
            ))
        ],
        "generated_code": updated_code,
        "written_files": written_files,
        "human_feedback": "",
        "feedback_target": "",
        "phase": "review_dev",
    }


# ============================================================
# ✅ Post-Approval Handler
# ============================================================

def run_developer_approved(state: dict) -> dict:
    """Nach Human OK: Weiter zum Tester."""
    task = state.get("current_task")

    print("\n" + "=" * 60)
    print("✅  CODE APPROVED – Weiter zum Tester")
    print("=" * 60)
    print(f"  📋 Task: {task.id if task else 'N/A'}")
    print(f"  ➡️  Weiter zum Tester...")
    print("=" * 60)

    _update_github_status(task, "Review")

    return {
        "messages": [
            AIMessage(content=(
                "✅ Code approved: " + (task.id if task else "N/A") + "\n"
                "🧪 Weiter zum Tester..."
            ))
        ],
        "phase": "test",
    }


# ============================================================
# ❌ Post-Rejection Handler
# ============================================================

def run_developer_rejected(state: dict) -> dict:
    """Nach Human NICHT OK: Zurück zum Developer mit Feedback."""
    task = state.get("current_task")
    feedback = state.get("human_feedback", "")

    print("\n" + "=" * 60)
    print("❌  CODE REJECTED – Feedback-Loop")
    print("=" * 60)
    print(f"  📋 Task: {task.title if task else 'N/A'}")
    print(f"  📝 Feedback: {feedback[:120]}...")
    print("=" * 60)

    return {
        "messages": [
            AIMessage(content=(
                "❌ Code rejected: " + (task.id if task else "N/A") + "\n"
                "📝 Feedback: " + feedback[:200] + "\n"
                "🔄 Developer überarbeitet..."
            ))
        ],
        "phase": "review_dev_rejected",
    }
