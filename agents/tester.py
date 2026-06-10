# agents/tester.py

import os
import re
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from config.settings import settings
from tools.file_tools import run_build, write_generated_code
from tools.github_tools import set_project_item_status, add_issue_comment


# ============================================================
# 🤖 LLM & Prompt Setup
# ============================================================

llm = ChatOpenAI(model=settings.default_model, temperature=0)

_prompt_path = os.path.join(settings.prompts_dir, "tester_prompt.md")
_system_prompt = open(_prompt_path, encoding="utf-8").read()
_system_prompt = _system_prompt.replace("{", "{{").replace("}", "}}")

tester_prompt = ChatPromptTemplate.from_messages([
    ("system", _system_prompt),
    ("human", "{context}"),
])

tester_chain = tester_prompt | llm


# ============================================================
# 📏 Konstanten
# ============================================================

MAX_BUILD_OUTPUT_CHARS = 15000
MAX_CODE_CONTEXT_CHARS = 40000
MAX_CONTEXT_CHARS = 120000
DOCS_BASE_PATH = "documentation/"


# ============================================================
# 📏 Hilfsfunktionen
# ============================================================

def _truncate_build_output(build_output: str) -> str:
    """Kürzt Build-Output intelligent – behält Fehler am Ende."""
    if len(build_output) <= MAX_BUILD_OUTPUT_CHARS:
        return build_output
    return (
        build_output[:500]
        + "\n\n[... TRUNCATED ...]\n\n"
        + build_output[-(MAX_BUILD_OUTPUT_CHARS - 500):]
    )


def _build_code_summary(generated_code: dict[str, str]) -> str:
    """Erstellt eine kompakte Code-Zusammenfassung für den Context."""
    if not generated_code:
        return "Kein generierter Code vorhanden."

    parts = []
    total_chars = 0

    for path, code in generated_code.items():
        if total_chars > MAX_CODE_CONTEXT_CHARS:
            remaining = len(generated_code) - len(parts)
            parts.append(
                "\n// ... weitere " + str(remaining) + " Dateien truncated"
            )
            break

        truncated = code[:2000] if len(code) > 2000 else code
        if len(code) > 2000:
            truncated += "\n// ... [TRUNCATED – " + str(len(code)) + " chars total]"

        parts.append("// ── " + path + " ──\n" + truncated)
        total_chars += len(truncated)

    return "\n\n".join(parts)


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
        print(f"  📊 GitHub Status → {status}")


def _add_test_comment(task, comment_body: str):
    issue_number = _get_issue_number(task)
    if issue_number:
        add_issue_comment(issue_number, comment_body)


# ============================================================
# 🔍 Parser: Test-Dateien (.kt)
# ============================================================

def _parse_test_files(llm_content: str) -> dict[str, str]:
    """
    Parst ### DATEI: *.kt Test-Dateien aus dem LLM-Output.
    Gleicher Parser wie Developer – nur Test-Dateien werden genommen.
    """
    files = {}
    pattern = r"### DATEI:\s*(.+?)\n```\w*\n(.*?)```"
    matches = re.findall(pattern, llm_content, re.DOTALL)

    for filepath, code in matches:
        filepath = filepath.strip().lstrip("./").replace("//", "/")

        if len(filepath) > 300 or "\n" in filepath:
            continue

        # Nur Test-Dateien akzeptieren
        if "/test/" in filepath and filepath.endswith(".kt"):
            files[filepath] = code.strip()

    if files:
        print(f"  🧪 {len(files)} Test-Dateien geparst:")
        for f in files:
            print(f"     • {f}")
    else:
        print(f"  ℹ️ Keine Test-Dateien aus LLM-Output geparst")

    return files


# ============================================================
# 🔍 Parser: Dokumentation (.md)
# ============================================================

def _parse_documentation(llm_content: str) -> str | None:
    """Extrahiert die Markdown-Dokumentation aus dem LLM-Output."""
    patterns = [
        r"###\s*\d+\.\s*Dokumentation.*?```markdown\s*\n(.*?)```",
        r"##\s*Dokumentation.*?```markdown\s*\n(.*?)```",
        r"(##\s*TASK-\d+:.*?)(?=\n###\s*\d+\.|\n##\s*Fix|\Z)",
    ]
    for pattern in patterns:
        match = re.search(pattern, llm_content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


# ============================================================
# 📝 Dokumentation schreiben (eine Datei, ergänzen)
# ============================================================

def _write_documentation(task, documentation: str, task_index: int) -> str:
    """
    Schreibt Doku als neuen Abschnitt in EINE gemeinsame .md Datei.
    Bestehende Dokumentation wird NICHT gelöscht – nur ergänzt
    oder bei gleichem Task aktualisiert.
    """
    docs_dir = Path(DOCS_BASE_PATH)
    docs_dir.mkdir(parents=True, exist_ok=True)

    doc_path = docs_dir / "development_docs.md"

    # Bestehende Doku laden
    existing = ""
    if doc_path.exists():
        existing = doc_path.read_text(encoding="utf-8")

    # Prüfen ob dieser Task schon dokumentiert ist
    if task.id in existing:
        # Task existiert schon → Abschnitt aktualisieren
        pattern = r"(## " + re.escape(task.id) + r":.*?)(?=\n## TASK-|\Z)"
        match = re.search(pattern, existing, re.DOTALL)
        if match:
            existing = re.sub(pattern, documentation, existing, flags=re.DOTALL)
            print(f"  📝 Dokumentation aktualisiert für {task.id}")
        else:
            existing += "\n\n" + documentation
            print(f"  📝 Dokumentation ergänzt für {task.id}")
    else:
        # Neuer Task → anhängen
        if not existing:
            existing = (
                "# " + settings.app_name + " – Entwicklungs-Dokumentation\n\n"
                "Automatisch generierte Dokumentation der Entwicklungsschritte.\n\n"
                "---\n\n"
            )
        existing += documentation + "\n\n---\n\n"
        print(f"  📝 Dokumentation hinzugefügt für {task.id}")

    doc_path.write_text(existing, encoding="utf-8")
    return str(doc_path)


# ============================================================
# 🔨 Build Runner
# ============================================================

def _execute_build(task, retry_count: int) -> tuple[str, bool]:
    """Führt den Build im Projekt aus."""
    print(f"\n⚙️  Starte Build: {settings.build_command}...")

    build_output = run_build.invoke({})

    real_build_success = "EXIT: 0" in build_output

    status_icon = "✅" if real_build_success else "❌"
    print(f"  {status_icon} Build: {'PASS' if real_build_success else 'FAIL'}")

    if not real_build_success:
        print(f"\n  📋 Fehler-Output (letzte 1500 Zeichen):")
        print(f"  {'─' * 50}")
        print(f"  {build_output[-1500:]}")
        print(f"  {'─' * 50}\n")

    # Build-Log speichern
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / ("build_" + task.id + "_retry" + str(retry_count) + ".log")
    log_file.write_text(build_output, encoding="utf-8")
    print(f"  📄 Build-Log: {log_file}")

    return build_output, real_build_success


# ============================================================
# 🧪 Tester Node – Hauptfunktion
# ============================================================

def run_tester(state: dict) -> dict:
    """
    🧪 Tester Node:
      - Führt Build im Projekt aus
      - LLM analysiert Build-Output + Code-Qualität
      - Bei PASS: Echte Test-.kt Dateien + Doku ergänzen
      - Bei FAIL: Fix-Vorschläge für Developer
      - Alle Anweisungen stehen im tester_prompt.md
    """
    task = state.get("current_task")

    if not task:
        return {
            "messages": [AIMessage(content="⚠️ Kein Task zum Testen")],
            "phase": "review_pr",
            "build_success": False,
        }

    retry_count = state.get("retry_count", 0)
    max_retries = settings.max_retries
    generated_code = state.get("generated_code", {})
    branch = state.get("current_branch", "")

    # ── Console Header ──
    print("\n" + "=" * 60)
    print("🧪  TESTER")
    print("=" * 60)
    print(f"\n📋 Task: {task.id} – {task.title}")
    print(f"🌿 Branch: {branch}")
    if retry_count > 0:
        print(f"🔄 Retry #{retry_count}/{max_retries}")

    # ════════════════════════════════════════════════════════
    # 1️⃣ Build ausführen
    # ════════════════════════════════════════════════════════
    build_output, real_build_success = _execute_build(task, retry_count)

    # ════════════════════════════════════════════════════════
    # 2️⃣ Context aufbauen
    # ════════════════════════════════════════════════════════
    truncated_build = _truncate_build_output(build_output)
    code_summary = _build_code_summary(generated_code)

    context_parts = []

    # Task-Daten
    context_parts.append(
        "## 📋 Task\n"
        "- **ID:** " + task.id + "\n"
        "- **Titel:** " + task.title + "\n"
        "- **Beschreibung:** " + task.description + "\n"
        "- **Branch:** " + branch + "\n"
        "- **Retry:** " + str(retry_count) + "/" + str(max_retries) + "\n"
    )

    # Build Ergebnis
    build_status = "ERFOLGREICH" if real_build_success else "FEHLGESCHLAGEN"
    context_parts.append(
        "## ⚙️ Build Ergebnis\n"
        "- **Befehl:** `" + settings.build_command + "`\n"
        "- **Status:** " + build_status + "\n\n"
        "### Build-Output:\n"
        "```\n" + truncated_build + "\n```\n"
    )

    # Generierter Code
    file_list = "\n".join("- `" + f + "`" for f in generated_code.keys())
    context_parts.append(
        "## 💻 Implementierter Code\n"
        "**Dateien (" + str(len(generated_code)) + "):**\n"
        + file_list + "\n\n"
        "### Code:\n" + code_summary + "\n"
    )

    # Planner-Entscheidungen
    planner_decisions = state.get("planner_decisions", [])
    if planner_decisions:
        dec_str = "\n".join(
            "- " + d.component + " → " + d.decision
            for d in planner_decisions
        )
        context_parts.append(
            "## 🏗️ Planner-Vorgaben:\n" + dec_str + "\n"
        )

    # Bestehende Dokumentation
    existing_docs = _load_existing_docs()
    if existing_docs:
        context_parts.append(
            "## 📝 Bestehende Dokumentation (nicht löschen, nur ergänzen):\n"
            + existing_docs[-3000:] + "\n"
        )

    context = "\n".join(context_parts)
    context = _truncate_context(context)

    # ════════════════════════════════════════════════════════
    # 3️⃣ LLM aufrufen
    # ════════════════════════════════════════════════════════
    print(f"  🤖 Rufe LLM auf (Context: {len(context)} chars)...")
    result = tester_chain.invoke({"context": context})

    # ════════════════════════════════════════════════════════
    # 4️⃣ Ergebnis auswerten
    # ════════════════════════════════════════════════════════
    llm_says_pass = "BUILD: PASS" in result.content.upper()
    build_success = real_build_success

    if real_build_success and not llm_says_pass:
        print(f"  ⚠️ LLM hat Bedenken, aber Build OK → akzeptiert")
    if not real_build_success and llm_says_pass:
        print(f"  ⚠️ LLM sagt PASS, aber Build FAILED → abgelehnt")

    print(f"\n  🧪 Gesamtergebnis: {'✅ PASS' if build_success else '❌ FAIL'}")

    # ════════════════════════════════════════════════════════
    # 5️⃣ Bei PASS: Test-Dateien + Dokumentation
    # ════════════════════════════════════════════════════════
    doc_path = None
    test_files_written = []

    if build_success:
        doc_path, test_files_written = _generate_artifacts(
            task, state, result.content
        )

    # ════════════════════════════════════════════════════════
    # 6️⃣ GitHub kommentieren
    # ════════════════════════════════════════════════════════
    _comment_github(task, build_success, build_output, result.content,
                    retry_count, max_retries, doc_path, test_files_written)

    # ════════════════════════════════════════════════════════
    # 7️⃣ Console-Ausgabe
    # ════════════════════════════════════════════════════════
    print(f"\n  🤖 LLM-Analyse (Auszug):")
    print(f"  {'─' * 50}")
    print(f"  {result.content[-500:]}")
    print(f"  {'─' * 50}")
    if doc_path:
        print(f"\n  📝 Dokumentation: {doc_path}")
    if test_files_written:
        print(f"  🧪 Test-Dateien: {len(test_files_written)}")
        for f in test_files_written:
            print(f"     • {f}")

    # ════════════════════════════════════════════════════════
    # 8️⃣ Routing & State
    # ════════════════════════════════════════════════════════
    return _build_tester_state(
        task, state, build_output, result.content,
        build_success, retry_count, max_retries,
        doc_path, test_files_written,
    )


# ============================================================
# 📝 Bestehende Doku laden (für Context)
# ============================================================

def _load_existing_docs() -> str:
    """Lädt bestehende Dokumentation damit der Tester sie kennt."""
    doc_path = Path(DOCS_BASE_PATH) / "development_docs.md"
    if doc_path.exists():
        return doc_path.read_text(encoding="utf-8")
    return ""


# ============================================================
# 📦 Artifact Generation
# ============================================================

def _generate_artifacts(task, state, llm_content) -> tuple:
    """
    Generiert zwei Arten von Artefakten:
    - Test-Dateien (.kt) → ins Projekt
    - Dokumentation (.md) → in documentation/development_docs.md (ergänzen)
    """
    doc_path = None
    test_files_written = []

    # ── Test-.kt Dateien parsen und schreiben ──
    test_files = _parse_test_files(llm_content)
    if test_files:
        test_files_written = write_generated_code(test_files)
        print(f"  🧪 {len(test_files_written)} Test-Dateien ins Projekt geschrieben")

    # ── Dokumentation parsen und ergänzen (NICHT überschreiben!) ──
    documentation = _parse_documentation(llm_content)
    if documentation:
        task_index = len(state.get("completed_tasks", [])) + 1
        doc_path = _write_documentation(task, documentation, task_index)
    else:
        print(f"  ⚠️ Keine Dokumentation aus LLM-Output geparst")

    return doc_path, test_files_written


# ============================================================
# 💬 GitHub Kommentare
# ============================================================

def _comment_github(task, build_success, build_output, llm_content,
                    retry_count, max_retries, doc_path, test_files_written):
    """Kommentiert das GitHub Issue mit dem Testergebnis."""
    if build_success:
        _update_github_status(task, "Review")

        doc_info = ""
        if doc_path:
            doc_info = "\n📝 Dokumentation ergänzt: `" + doc_path + "`"

        test_info = ""
        if test_files_written:
            test_info = (
                "\n🧪 Test-Dateien (" + str(len(test_files_written)) + "):\n"
                + "\n".join("- `" + f + "`" for f in test_files_written)
            )

        _add_test_comment(task, (
            "## 🧪 Tester – Build BESTANDEN ✅\n\n"
            "**Build:** Erfolgreich (`" + settings.build_command + "`)\n"
            "**Retry:** " + str(retry_count) + "/" + str(max_retries) + "\n"
            + doc_info + test_info + "\n\n"
            "### LLM-Analyse (Auszug):\n"
            + llm_content[:800] + "\n\n"
            "⏳ Wartet auf Human Review."
        ))
    else:
        error_excerpt = build_output[-500:] if build_output else "Kein Output"
        _add_test_comment(task, (
            "## 🧪 Tester – Build FEHLGESCHLAGEN ❌\n\n"
            "**Build:** Fehlgeschlagen (`" + settings.build_command + "`)\n"
            "**Retry:** " + str(retry_count) + "/" + str(max_retries) + "\n\n"
            "### Fehler-Auszug:\n```\n" + error_excerpt + "\n```\n\n"
            "### LLM Fix-Vorschläge:\n" + llm_content[:800] + "\n"
        ))


# ============================================================
# 🔀 State Builder
# ============================================================

def _build_tester_state(
    task, state, build_output, llm_content,
    build_success, retry_count, max_retries,
    doc_path, test_files_written,
) -> dict:
    """Baut den Return-State basierend auf Build-Ergebnis."""
    truncated_build = _truncate_build_output(build_output)

    test_report = (
        "## Build\n"
        "Befehl: `" + settings.build_command + "`\n"
        "Status: " + ("PASS" if build_success else "FAIL") + "\n"
        "```\n" + truncated_build + "\n```\n\n"
        "## LLM Analyse\n" + llm_content
    )

    written_files = list(state.get("written_files", []))
    if doc_path:
        written_files.append(doc_path)
    written_files.extend(test_files_written)

    if build_success:
        # ── PASS → Human Review PR ──
        test_info = ""
        if test_files_written:
            test_info = (
                "🧪 Tests: " + str(len(test_files_written)) + " Dateien\n"
            )

        print(f"\n  ✅ Build bestanden → Warte auf Human Review")
        print("=" * 60)

        return {
            "messages": [AIMessage(content=(
                "🧪 **" + task.id + ": ✅ BUILD PASS**\n\n"
                "Build erfolgreich.\n"
                + test_info
                + ("📝 Doku ergänzt: `" + doc_path + "`\n" if doc_path else "")
                + "\n⏸️ Warte auf Human Review..."
            ))],
            "test_results": test_report,
            "build_success": True,
            "written_files": written_files,
            "phase": "review_pr",
        }

    # ── FAIL ──
    new_retry = retry_count + 1

    if new_retry >= max_retries:
        # ── Max Retries → Human muss entscheiden ──
        print(f"\n  ⚠️ Max Retries ({max_retries}) erreicht → Human Review")
        print("=" * 60)

        return {
            "messages": [AIMessage(content=(
                "🧪 **" + task.id + ": ❌ FAIL nach "
                + str(max_retries) + " Retries**\n\n"
                "Build fehlgeschlagen. Max Retries erreicht.\n\n"
                "**Letzter Fehler:**\n```\n"
                + build_output[-500:] + "\n```"
            ))],
            "test_results": test_report,
            "build_success": False,
            "retry_count": new_retry,
            "written_files": written_files,
            "phase": "review_pr",
        }

    # ── Auto-Retry → Developer ──
    print(f"\n  🔄 Auto-Retry → Developer ({new_retry}/{max_retries})")
    print("=" * 60)

    return {
        "messages": [AIMessage(content=(
            "🧪 **" + task.id + ": ❌ FAIL → Retry "
            + str(new_retry) + "/" + str(max_retries) + "**\n\n"
            "Build fehlgeschlagen. Developer bekommt Fehlermeldung."
        ))],
        "test_results": test_report,
        "build_success": False,
        "retry_count": new_retry,
        "written_files": written_files,
        "human_feedback": "",
        "phase": "develop_retry",
    }
