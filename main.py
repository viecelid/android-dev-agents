# main.py

import os
import time
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from langchain_openai import ChatOpenAI
from graph import app
from state import AgentState
from config.settings import settings
from tools.file_tools import (
    get_file_tree,
    read_all_files,
    is_project_initialized,
)

console = Console()

THREAD_ID = "dev-v1"
MAX_TOTAL_CODE_CHARS = 200000


# ============================================================
# 📂 Projekt laden & analysieren
# ============================================================

def load_project() -> dict:
    """
    Lädt das Projekt-Repo und analysiert den aktuellen Stand.
    Falls leer/nicht vorhanden → signalisiert Scaffold-Bedarf.
    """

    console.print(f"\n[bold]📂 Lade Projekt...[/bold]")
    console.print(f"   Pfad: {settings.repo_path}")
    console.print(f"   Repo: {settings.github_repo}")

    repo_exists = os.path.exists(settings.repo_path)
    initialized = is_project_initialized() if repo_exists else False

    if not repo_exists:
        console.print(f"  🆕 Verzeichnis existiert noch nicht – wird erstellt.")
        os.makedirs(settings.repo_path, exist_ok=True)
        return {
            "files": [],
            "code_contents": "",
            "project_initialized": False,
        }

    if not initialized:
        console.print(f"  📂 Verzeichnis existiert, aber kein Projekt erkannt.")
        return {
            "files": [],
            "code_contents": "",
            "project_initialized": False,
        }

    # ── Projekt einlesen ──
    files = get_file_tree()
    code_contents = read_all_files()

    console.print(f"  ✅ Projekt erkannt ({len(files)} Dateien)")
    for f in files[:30]:
        console.print(f"     • {f}")
    if len(files) > 30:
        console.print(f"     ... und {len(files) - 30} weitere")

    # Code als String für den Planner
    code_str = "\n\n".join(
        f"### {path}\n```{path.split('.')[-1]}\n{code}\n```"
        for path, code in code_contents.items()
    )

    if len(code_str) > MAX_TOTAL_CODE_CHARS:
        console.print(
            f"  ⚠️ Code-Inhalt truncated: "
            f"{len(code_str)} → {MAX_TOTAL_CODE_CHARS} chars"
        )
        code_str = code_str[:MAX_TOTAL_CODE_CHARS] + "\n\n[... TRUNCATED ...]"

    console.print(f"  📝 Code-Inhalt: {len(code_str)} chars geladen")

    return {
        "files": files,
        "code_contents": code_str,
        "project_initialized": True,
    }


# ============================================================
# 🔍 Initiale Projekt-Analyse (ohne Graph)
# ============================================================

def _run_initial_analysis(project_data: dict):
    """
    Zeigt eine Projekt-Analyse direkt im Terminal an.
    Wird beim ersten Start aufgerufen – kein Graph-Durchlauf nötig.
    """
    console.print(
        "\n[bold cyan]🔍 Analysiere bestehendes Projekt...[/bold cyan]\n"
    )

    llm = ChatOpenAI(model=settings.default_model, temperature=0)

    # Code-Preview für Context (max 30k chars)
    code_preview = project_data["code_contents"][:30000]
    file_list = "\n".join(f"- {f}" for f in project_data["files"])

    response = llm.invoke(
        f"Du bist ein erfahrener Android Software Architect.\n\n"
        f"Analysiere dieses Projekt und gib eine kompakte Zusammenfassung:\n\n"
        f"1. **Projekt-Struktur** (Packages, Module, Schichten)\n"
        f"2. **Features** (Was kann die App bereits?)\n"
        f"3. **Tech-Stack** (Libraries, Patterns, Architektur)\n"
        f"4. **Offene Punkte / Verbesserungspotenzial**\n\n"
        f"Halte dich kurz und präzise. Nutze Markdown-Formatierung.\n\n"
        f"---\n\n"
        f"## Projekt: {settings.app_name} ({settings.app_package})\n\n"
        f"### Dateien ({len(project_data['files'])}):\n{file_list}\n\n"
        f"### Code:\n{code_preview}"
    )

    console.print(Panel(
        response.content,
        title=f"🔍 {settings.app_name} – Projekt-Analyse",
        style="bold cyan",
    ))


# ============================================================
# 🖨️ UI-Ausgabe
# ============================================================

def _print_phase(event: dict):
    """Zeigt die aktuelle Phase an."""
    phase = event.get("phase", "")
    task = event.get("current_task")

    phase_icons = {
        "analyze":              "🔍 Projekt-Analyse",
        "scaffold":             "🏗️  Projekt-Scaffold (Hello World)",
        "await_instruction":    "⏳ Warte auf Anweisung...",
        "plan":                 "🏗️  Planner/Architect",
        "review_plan":          "👤 Review: Plan",
        "review_plan_approved": "✅ Plan freigegeben",
        "review_plan_rejected": "🔄 Plan überarbeiten",
        "develop":              "💻 Developer",
        "develop_retry":        "🔄 Developer Retry",
        "review_dev":           "👤 Review: Code",
        "review_dev_approved":  "✅ Code freigegeben → Tester",
        "review_dev_rejected":  "🔄 Code überarbeiten",
        "test":                 "🧪 Tester",
        "review_pr":            "👤 Review: Test-Ergebnis / PR",
        "review_pr_approved":   "✅ PR freigegeben → Commit",
        "review_pr_rejected":   "🔄 PR überarbeiten",
        "committed":            "📦 Committed & PR erstellt",
        "done":                 "🎉 Task abgeschlossen!",
    }

    label = phase_icons.get(phase, f"📍 {phase}")

    if task and hasattr(task, "id"):
        console.print(f"[bold cyan]{label}[/bold cyan] [dim]({task.id})[/dim]")
    elif phase:
        console.print(f"[bold cyan]{label}[/bold cyan]")


def _handle_interrupt():
    """Behandelt Ctrl+C – Checkpoint wird automatisch gespeichert."""
    console.print(Panel(
        "⏸️  Entwicklung pausiert (Ctrl+C)\n\n"
        "Checkpoint wurde automatisch gespeichert.\n"
        "Starte das Script neu um fortzufahren:\n\n"
        "   [cyan]python main.py[/cyan]\n\n"
        "Thread-ID [cyan]" + THREAD_ID + "[/cyan] wird automatisch fortgesetzt.",
        style="bold yellow",
    ))


def _print_completed_tasks(completed: list[dict]):
    """Zeigt alle abgeschlossenen Tasks an."""
    for t in completed:
        console.print(f"   ✅ {t['id']} – {t['title']}")
        console.print(f"      PR: [cyan]{t.get('pr_url', '?')}[/cyan]")


def _print_project_summary(project_data: dict):
    """Zeigt die Projekt-Zusammenfassung an."""
    console.print(f"\n📊 Projekt-Status:")
    console.print(
        f"   📂 Dateien: {len(project_data['files'])} "
        f"({', '.join(settings.file_extensions)})"
    )
    console.print(
        f"   🏗️  Initialisiert: "
        f"{'Ja' if project_data['project_initialized'] else 'Nein'}"
    )
    console.print(f"   👤 Du gibst Anweisungen im Terminal")
    console.print(f"   🏗️  Planner plant Tasks basierend auf deinen Anweisungen")
    console.print(f"   💻 Developer implementiert nach deinem OK")
    console.print(f"   🧪 Tester prüft mit `{settings.build_command}`")
    console.print(f"   📦 Commit erst nach Tester + deinem OK\n")


# ============================================================
# 🔄 Resume-Logik
# ============================================================

def _try_resume(config: dict) -> bool:
    """
    Versucht einen bestehenden Checkpoint fortzusetzen.
    Returns: True wenn fortgesetzt/beendet, False wenn neu starten.
    """
    try:
        state = app.get_state(config)
        values = (
            state.values
            if hasattr(state, "values")
            else state.get("values", {})
        )
        phase = values.get("phase", "")

        # ── "done" oder leer = fertig → direkt zur development_loop ──
        if phase == "done" or phase == "":
            return False

        # ── Checkpoint vorhanden → Fortsetzen? ──
        if phase and phase != "await_instruction":
            task = values.get("current_task")
            completed = values.get("completed_tasks", [])
            retry_count = values.get("retry_count", 0)

            resume_info = (
                f"🔄 Fortsetzen vom letzten Checkpoint\n\n"
                f"   Phase: [cyan]{phase}[/cyan]\n"
            )
            if task:
                resume_info += f"   Task: [cyan]{task.id} – {task.title}[/cyan]\n"
            resume_info += (
                f"   Branch: [cyan]{values.get('current_branch', '?')}[/cyan]\n"
                f"   Erledigt: [green]{len(completed)}[/green] Tasks\n"
                f"   Retries: {retry_count}"
            )

            console.print(Panel(resume_info, style="bold blue"))

            if Confirm.ask("Fortfahren?"):
                console.print(
                    "\n[bold green]▶️  Graph wird fortgesetzt...[/bold green]\n"
                )
                try:
                    for event in app.stream(None, config, stream_mode="values"):
                        _print_phase(event)
                except KeyboardInterrupt:
                    _handle_interrupt()
                return True

            if Confirm.ask("🔄 Stattdessen neu starten?"):
                return False

            console.print("[yellow]Beendet.[/yellow]")
            return True

    except Exception:
        pass

    return False


# ============================================================
# 💬 Interaktive Entwicklungsschleife
# ============================================================

def development_loop(config: dict, project_data: dict):
    """
    Hauptschleife: Wartet auf Human-Anweisungen, startet den Graph pro Task.
    Jede Anweisung bekommt eine eigene Thread-ID um Checkpoint-Konflikte zu vermeiden.
    """

    # ── Initiale Projekt-Analyse (nur bei bestehendem Projekt) ──
    if project_data["project_initialized"]:
        if Confirm.ask("🔍 Projekt-Analyse anzeigen?", default=True):
            _run_initial_analysis(project_data)

    # ── Interaktive Loop starten ──
    console.print(Panel(
        "💬 [bold]Entwicklungsmodus aktiv[/bold]\n\n"
        "Gib deine Anweisungen ein (z.B. 'Füge einen Login-Screen hinzu').\n"
        "Der Planner erstellt einen Plan, den du reviewen kannst.\n\n"
        "Befehle:\n"
        "  [cyan]exit[/cyan] / [cyan]quit[/cyan] – Beenden\n"
        "  [cyan]status[/cyan] – Projekt-Status anzeigen\n"
        "  [cyan]Ctrl+C[/cyan] – Pausieren (Checkpoint wird gespeichert)",
        style="bold blue",
    ))

    completed_tasks = []
    task_counter = 0

    while True:
        # ── Auf Anweisung warten ──
        console.print()
        instruction = Prompt.ask(
            "[bold yellow]🎯 Was soll als nächstes gemacht werden?[/bold yellow]"
        )

        if not instruction.strip():
            continue

        if instruction.strip().lower() in ("exit", "quit", "q"):
            console.print("[yellow]👋 Beendet. Bis zum nächsten Mal![/yellow]")
            break

        if instruction.strip().lower() == "status":
            _print_project_summary(project_data)
            if completed_tasks:
                console.print("  📋 Erledigte Tasks dieser Session:")
                _print_completed_tasks(completed_tasks)
            continue

        # ── Neuer Thread pro Anweisung (verhindert Checkpoint-Konflikt) ──
        task_counter += 1
        task_config = {
            "configurable": {"thread_id": f"{THREAD_ID}-task-{task_counter}"},
            "recursion_limit": 100,
        }

        # ── Graph mit Anweisung starten ──
        console.print(
            f"\n[bold green]🤖 Starte Planung für:[/bold green] {instruction}\n"
        )

        initial_state = AgentState(
            messages=[],
            files=project_data["files"],
            code_contents=project_data["code_contents"],
            project_initialized=project_data["project_initialized"],
            human_instruction=instruction,
            completed_tasks=completed_tasks,
        )

        try:
            for event in app.stream(initial_state, task_config, stream_mode="values"):
                _print_phase(event)

            # ── Nach Task: Projekt neu einlesen ──
            project_data = load_project()
            # Erledigte Tasks aus State holen
            try:
                state = app.get_state(task_config)
                values = (
                    state.values
                    if hasattr(state, "values")
                    else state.get("values", {})
                )
                completed_tasks = values.get("completed_tasks", completed_tasks)
            except Exception:
                pass

        except KeyboardInterrupt:
            _handle_interrupt()
            break


# ============================================================
# 🚀 Hauptfunktion
# ============================================================

def run():
    """Startet oder setzt die Entwicklung fort."""

    console.print(Panel(
        f"🦟 [bold]{settings.app_name} – AI Development Agent[/bold]\n\n"
        f"Projekt: {settings.repo_path}\n"
        f"GitHub:  {settings.github_repo}\n"
        f"Sprache: {settings.language}\n"
        f"Build:   {settings.build_command}\n\n"
        "Multi-Agent System:\n"
        "  🏗️  Planner/Architect → plant Tasks nach deinen Anweisungen\n"
        "  💻 Developer → implementiert Code\n"
        "  🧪 Tester → prüft Build + Tests\n"
        "  👤 Du → gibst Anweisungen & reviewst\n\n"
        f"Thread-ID: [cyan]{THREAD_ID}[/cyan]",
        style="bold green",
    ))

    config = {
        "configurable": {"thread_id": THREAD_ID},
        "recursion_limit": 100,
    }

    # ── Resume-Check ──
    if _try_resume(config):
        return

    # ── Projekt laden ──
    project_data = load_project()

    # ── Falls kein Projekt vorhanden → Scaffold anbieten ──
    if not project_data["project_initialized"]:
        console.print(Panel(
            "🆕 Kein bestehendes Projekt erkannt.\n\n"
            "Optionen:\n"
            "  1. Neues Android-Projekt scaffolden (Hello World)\n"
            "  2. Manuell ein Projekt im Repo-Pfad ablegen und neu starten",
            style="bold yellow",
        ))

        if Confirm.ask("🏗️  Neues Projekt scaffolden?"):
            # Eigener Thread für Scaffold
            scaffold_config = {
                "configurable": {"thread_id": f"{THREAD_ID}-scaffold"},
                "recursion_limit": 100,
            }

            # Graph mit Scaffold-Anweisung starten
            initial_state = AgentState(
                messages=[],
                files=[],
                code_contents="",
                project_initialized=False,
                human_instruction=(
                    f"Erstelle ein neues Android-Projekt '{settings.app_name}' "
                    f"mit Package '{settings.app_package}', "
                    f"minSdk={settings.android_min_sdk}, "
                    f"targetSdk={settings.android_target_sdk}, "
                    f"compileSdk={settings.android_compile_sdk}. "
                    f"Verwende Kotlin, Jetpack Compose, Material3. "
                    f"Erstelle eine saubere Projekt-Struktur mit einer "
                    f"einfachen 'Hello World' MainActivity."
                ),
                completed_tasks=[],
            )

            console.print("\n[bold green]🤖 Scaffold wird erstellt...[/bold green]\n")

            try:
                for event in app.stream(initial_state, scaffold_config, stream_mode="values"):
                    _print_phase(event)
            except KeyboardInterrupt:
                _handle_interrupt()
                return

            # Projekt neu laden nach Scaffold
            project_data = load_project()
        else:
            console.print(
                f"[yellow]Lege ein Projekt in {settings.repo_path} ab "
                f"und starte neu.[/yellow]"
            )
            return

    # ── Projekt-Zusammenfassung ──
    _print_project_summary(project_data)

    # ── Interaktive Entwicklungsschleife starten ──
    development_loop(config, project_data)


# ============================================================
# 🏁 Entry Point
# ============================================================

if __name__ == "__main__":
    run()
