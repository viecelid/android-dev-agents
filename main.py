# main.py

import os
import json
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm
from langchain_openai import ChatOpenAI

from graph import app
from state import AgentState
from config.settings import settings
from tools.file_tools import (
    get_file_tree,
    read_all_files,
    is_project_initialized,
)
from utils.terminal_input import read_instruction

console = Console()

THREAD_ID = "dev-v1"
RECURSION_LIMIT = 100
MAX_TOTAL_CODE_CHARS = 200_000
SESSION_FILE = Path("checkpoints/session.json")
EXIT_COMMANDS = ("exit", "quit", "q")


# ============================================================
# 💾 Session State (persistent für Resume)
# ============================================================

def _load_session() -> dict:
    """Lädt den Session-State aus der JSON-Datei."""
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text())
        except Exception:
            pass
    return {"task_counter": 0, "active_thread": None, "completed_tasks": []}


def _save_session(session: dict):
    """Speichert den Session-State."""
    SESSION_FILE.parent.mkdir(exist_ok=True)
    SESSION_FILE.write_text(json.dumps(session, indent=2))


# ============================================================
# 🔧 Graph-Helfer
# ============================================================

def _thread_config(thread_id: str) -> dict:
    """Baut die LangGraph-Config für einen Thread."""
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }


def _get_state_values(config: dict) -> dict:
    """Liest die State-Werte des Checkpoints."""
    state = app.get_state(config)
    return getattr(state, "values", None) or {}


def _stream_graph(initial_state, config: dict):
    """Führt den Graph aus und zeigt die Phasen an."""
    for event in app.stream(initial_state, config, stream_mode="values"):
        _print_phase(event)


# ============================================================
# 📂 Projekt laden & analysieren
# ============================================================

def load_project() -> dict:
    """
    Lädt das Projekt-Repo und analysiert den aktuellen Stand.
    Falls leer/nicht vorhanden → signalisiert Scaffold-Bedarf.
    """
    console.print("\n[bold]📂 Lade Projekt...[/bold]")
    console.print(f"   Pfad: {escape(settings.repo_path)}")
    console.print(f"   Repo: {escape(settings.github_repo)}")

    empty = {"files": [], "code_contents": "", "project_initialized": False}

    if not os.path.exists(settings.repo_path):
        console.print("  🆕 Verzeichnis existiert noch nicht – wird erstellt.")
        os.makedirs(settings.repo_path, exist_ok=True)
        return empty

    if not is_project_initialized():
        console.print("  📂 Verzeichnis existiert, aber kein Projekt erkannt.")
        return empty

    # ── Projekt einlesen ──
    files = get_file_tree()
    code_contents = read_all_files()

    console.print(f"  ✅ Projekt erkannt ({len(files)} Dateien)")
    for f in files[:30]:
        console.print(f"     • {escape(f)}")
    if len(files) > 30:
        console.print(f"     ... und {len(files) - 30} weitere")

    # ── Code als String für den Planner ──
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
    """Zeigt eine Projekt-Analyse direkt im Terminal an."""
    console.print("\n[bold cyan]🔍 Analysiere bestehendes Projekt...[/bold cyan]\n")

    llm = ChatOpenAI(model=settings.default_model, temperature=0)

    code_preview = project_data["code_contents"][:30_000]
    file_list = "\n".join(f"- {f}" for f in project_data["files"])

    response = llm.invoke(
        "Du bist ein erfahrener Android Software Architect.\n\n"
        "Analysiere dieses Projekt und gib eine kompakte Zusammenfassung:\n\n"
        "1. **Projekt-Struktur** (Packages, Module, Schichten)\n"
        "2. **Features** (Was kann die App bereits?)\n"
        "3. **Tech-Stack** (Libraries, Patterns, Architektur)\n"
        "4. **Offene Punkte / Verbesserungspotenzial**\n\n"
        "Halte dich kurz und präzise. Nutze Markdown-Formatierung.\n\n"
        "---\n\n"
        f"## Projekt: {settings.app_name} ({settings.app_package})\n\n"
        f"### Dateien ({len(project_data['files'])}):\n{file_list}\n\n"
        f"### Code:\n{code_preview}"
    )

    # Markdown statt Rich-Markup → eckige Klammern im LLM-Output crashen nicht
    console.print(Panel(
        Markdown(response.content),
        title=f"🔍 {escape(settings.app_name)} – Projekt-Analyse",
        style="bold cyan",
    ))


# ============================================================
# 🖨️ UI-Ausgabe
# ============================================================

PHASE_LABELS = {
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
    "done":                 "🎉 Anweisung abgeschlossen!",
}


def _print_phase(event: dict):
    """Zeigt die aktuelle Phase an."""
    phase = event.get("phase", "")
    if not phase:
        return

    label = PHASE_LABELS.get(phase, f"📍 {phase}")
    task = event.get("current_task")

    if task and hasattr(task, "id"):
        console.print(f"[bold cyan]{label}[/bold cyan] [dim]({escape(task.id)})[/dim]")
    else:
        console.print(f"[bold cyan]{label}[/bold cyan]")


def _handle_interrupt():
    """Behandelt Ctrl+C während ein Task läuft – Checkpoint ist gespeichert."""
    console.print(Panel(
        "⏸️  Entwicklung pausiert (Ctrl+C)\n\n"
        "Checkpoint wurde automatisch gespeichert.\n"
        "Starte das Script neu um fortzufahren:\n\n"
        "   [cyan]python main.py[/cyan]\n\n"
        "Der letzte Task wird automatisch fortgesetzt.",
        style="bold yellow",
    ))


def _print_completed_tasks(completed: list[dict]):
    """Zeigt alle abgeschlossenen Tasks an."""
    for t in completed:
        console.print(f"   ✅ {escape(t.get('id', '?'))} – {escape(t.get('title', '?'))}")
        console.print(f"      PR: [cyan]{escape(t.get('pr_url', '?'))}[/cyan]")


def _print_project_summary(project_data: dict):
    """Zeigt die Projekt-Zusammenfassung an."""
    console.print("\n📊 Projekt-Status:")
    console.print(
        f"   📂 Dateien: {len(project_data['files'])} "
        f"({', '.join(settings.file_extensions)})"
    )
    console.print(
        f"   🏗️  Initialisiert: "
        f"{'Ja' if project_data['project_initialized'] else 'Nein'}"
    )
    console.print("   👤 Du gibst Anweisungen im Terminal")
    console.print("   🏗️  Planner plant Tasks basierend auf deinen Anweisungen")
    console.print("   💻 Developer implementiert nach deinem OK")
    console.print(f"   🧪 Tester prüft mit `{escape(settings.build_command)}`")
    console.print("   📦 Commit erst nach Tester + deinem OK\n")


# ============================================================
# 🔄 Resume-Logik
# ============================================================

def _try_resume() -> bool:
    """
    Versucht den letzten aktiven Task fortzusetzen.
    Returns:
        True  → User will beenden → run() soll stoppen
        False → Weiter zur development_loop
    """
    session = _load_session()
    active_thread = session.get("active_thread")
    if not active_thread:
        return False

    config = _thread_config(active_thread)

    def _clear_active_thread():
        session["active_thread"] = None
        _save_session(session)

    # ── Checkpoint lesen ──
    try:
        values = _get_state_values(config)
    except Exception:
        _clear_active_thread()
        return False

    phase = values.get("phase", "")
    if phase in ("", "done"):
        _clear_active_thread()
        return False

    # ── Offener Task gefunden ──
    task = values.get("current_task")
    completed = values.get("completed_tasks", [])

    resume_info = (
        "🔄 Offener Task gefunden\n\n"
        f"   Thread: [cyan]{escape(active_thread)}[/cyan]\n"
        f"   Phase: [cyan]{escape(phase)}[/cyan]\n"
    )
    if task:
        resume_info += f"   Task: [cyan]{escape(task.id)} – {escape(task.title)}[/cyan]\n"
    resume_info += (
        f"   Branch: [cyan]{escape(values.get('current_branch', '') or '?')}[/cyan]\n"
        f"   Erledigt: [green]{len(completed)}[/green] Tasks\n"
        f"   Retries: {values.get('retry_count', 0)}"
    )
    console.print(Panel(resume_info, style="bold blue"))

    # ── Fortsetzen ──
    if Confirm.ask("▶️  Task fortsetzen und fertig machen?"):
        console.print("\n[bold green]▶️  Graph wird fortgesetzt...[/bold green]\n")
        try:
            _stream_graph(None, config)
        except KeyboardInterrupt:
            _handle_interrupt()
            return True

        try:
            values = _get_state_values(config)
            session["completed_tasks"] = values.get("completed_tasks", completed)
        except Exception:
            pass

        _clear_active_thread()
        return False

    # ── Verwerfen oder beenden ──
    if Confirm.ask("🗑️  Task verwerfen und mit neuer Anweisung starten?"):
        _clear_active_thread()
        return False

    console.print("[yellow]👋 Beendet.[/yellow]")
    return True


# ============================================================
# 💬 Interaktive Entwicklungsschleife
# ============================================================

def development_loop(project_data: dict):
    """
    Hauptschleife: Wartet auf Human-Anweisungen, startet den Graph pro Anweisung.
    Jede Anweisung bekommt eine eigene Thread-ID (keine Checkpoint-Konflikte).
    """
    session = _load_session()
    completed_tasks = session.get("completed_tasks", [])
    task_counter = session.get("task_counter", 0)

    # ── Initiale Projekt-Analyse (nur bei bestehendem Projekt) ──
    if project_data["project_initialized"] and Confirm.ask(
        "🔍 Projekt-Analyse anzeigen?", default=False
    ):
        _run_initial_analysis(project_data)

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

    while True:
        # ── Auf Anweisung warten (Ctrl+C / Ctrl+D sauber abfangen) ──
        console.print()
        try:
            instruction, images = read_instruction(
                "🎯 Was soll als nächstes gemacht werden?"
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]👋 Beendet. Bis zum nächsten Mal![/yellow]")
            break

        if not instruction:
            continue

        command = instruction.lower()

        if command in EXIT_COMMANDS:
            console.print("[yellow]👋 Beendet. Bis zum nächsten Mal![/yellow]")
            break

        if command == "status":
            _print_project_summary(project_data)
            if completed_tasks:
                console.print("  📋 Erledigte Tasks dieser Session:")
                _print_completed_tasks(completed_tasks)
            continue

        # ── Neuer Thread pro Anweisung ──
        task_counter += 1
        thread_id = f"{THREAD_ID}-task-{task_counter}"
        config = _thread_config(thread_id)

        # ── Aktiven Thread speichern (für Resume bei Crash/Ctrl+C) ──
        session["task_counter"] = task_counter
        session["active_thread"] = thread_id
        session["completed_tasks"] = completed_tasks
        _save_session(session)

        console.print(
            f"\n[bold green]🤖 Starte Planung für:[/bold green]\n{escape(instruction)}\n"
        )
        if images:
            console.print(
                f"  🖼️ {len(images)} Bild(er) erkannt: {escape(', '.join(images))}"
            )

        initial_state = AgentState(
            messages=[],
            files=project_data["files"],
            code_contents=project_data["code_contents"],
            project_initialized=project_data["project_initialized"],
            human_instruction=instruction,
            instruction_images=images,
            completed_tasks=completed_tasks,
            tasks=[],
            current_task=None,
        )

        try:
            _stream_graph(initial_state, config)
        except KeyboardInterrupt:
            _handle_interrupt()
            break

        # ── Nach der Anweisung: Projekt neu einlesen ──
        project_data = load_project()

        try:
            completed_tasks = _get_state_values(config).get(
                "completed_tasks", completed_tasks
            )
        except Exception:
            pass

        # ── Session updaten: kein aktiver Thread mehr ──
        session["active_thread"] = None
        session["completed_tasks"] = completed_tasks
        _save_session(session)


# ============================================================
# 🏗️ Scaffold (neues Projekt)
# ============================================================

def _run_scaffold() -> bool:
    """
    Erstellt ein neues Android-Projekt über den Graph.
    Returns: True wenn fertig, False wenn abgebrochen (Ctrl+C).
    """
    thread_id = f"{THREAD_ID}-scaffold"
    config = _thread_config(thread_id)

    session = _load_session()
    session["active_thread"] = thread_id
    _save_session(session)

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
        instruction_images=[],
        completed_tasks=[],
        tasks=[],
        current_task=None,
    )

    console.print("\n[bold green]🤖 Scaffold wird erstellt...[/bold green]\n")

    try:
        _stream_graph(initial_state, config)
    except KeyboardInterrupt:
        _handle_interrupt()
        return False

    session = _load_session()
    session["active_thread"] = None
    _save_session(session)
    return True


# ============================================================
# 🚀 Hauptfunktion
# ============================================================

def run():
    """Startet oder setzt die Entwicklung fort."""
    console.print(Panel(
        f"[bold]{escape(settings.app_name)} – AI Development Agent[/bold]\n\n"
        f"Projekt: {escape(settings.repo_path)}\n"
        f"GitHub:  {escape(settings.github_repo)}\n"
        f"Sprache: {escape(settings.language)}\n"
        f"Build:   {escape(settings.build_command)}\n\n"
        "Multi-Agent System:\n"
        "  🏗️  Planner/Architect → plant Tasks nach deinen Anweisungen\n"
        "  💻 Developer → implementiert Code\n"
        "  🧪 Tester → prüft Build + Tests\n"
        "  👤 Du → gibst Anweisungen & reviewst\n\n"
        f"Session: [cyan]{SESSION_FILE}[/cyan]",
        style="bold green",
    ))

    # ── Resume-Check ──
    if _try_resume():
        return

    # ── Projekt laden ──
    project_data = load_project()

    # ── Kein Projekt → Scaffold anbieten ──
    if not project_data["project_initialized"]:
        console.print(Panel(
            "🆕 Kein bestehendes Projekt erkannt.\n\n"
            "Optionen:\n"
            "  1. Neues Android-Projekt scaffolden (Hello World)\n"
            "  2. Manuell ein Projekt im Repo-Pfad ablegen und neu starten",
            style="bold yellow",
        ))

        if not Confirm.ask("🏗️  Neues Projekt scaffolden?"):
            console.print(
                f"[yellow]Lege ein Projekt in {escape(settings.repo_path)} ab "
                f"und starte neu.[/yellow]"
            )
            return

        if not _run_scaffold():
            return

        project_data = load_project()

    # ── Los geht's ──
    _print_project_summary(project_data)
    development_loop(project_data)


# ============================================================
# 🏁 Entry Point
# ============================================================

if __name__ == "__main__":
    try:
        run()
    except (KeyboardInterrupt, EOFError):
        # Fängt Ctrl+C/Ctrl+D überall sonst ab (z.B. bei Confirm.ask oder im Review)
        console.print("\n[yellow]👋 Abgebrochen. Checkpoint bleibt erhalten.[/yellow]")
