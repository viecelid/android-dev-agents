# utils/terminal_input.py
"""
Eingabe über mehrere Zeilen, mit Paste und Bildern (Docker-tauglich).

  Enter                 → Absenden
  Option+Enter / Ctrl+J → Neue Zeile
  Cmd+V (Text)          → Fügt den ganzen Block ein, inkl. Zeilenumbrüchen
  Ctrl+T / Ctrl+V       → Fügt das neueste Bild aus dem Inbox-Ordner ein
                          (Ctrl+V nur, wenn das Terminal die Taste nicht abfängt)
  @shot                 → Platzhalter im Text, wird beim Absenden durch das
                          neueste Bild ersetzt (funktioniert in jedem Terminal)
  Drag & Drop           → Bilddatei aus dem Finder (Ordner muss gemountet sein)
  Ctrl+X Ctrl+E         → Eingabe im $EDITOR öffnen
"""

import os
import re
import time
import base64
import mimetypes
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.markup import escape

console = Console()

BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_FILE = BASE_DIR / "checkpoints" / "input_history.txt"

INBOX_DIR = Path(os.getenv("IMAGE_INBOX", "/inbox"))
INBOX_MAX_AGE = int(os.getenv("IMAGE_INBOX_MAX_AGE", "600"))  # Sekunden
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SHOT_PLACEHOLDER = "@shot"
MAX_PATH_LEN = 1024


# ── 📸 Neuestes Bild aus der Inbox ─────────────────────────
def _latest_inbox_image() -> str | None:
    """Gibt den Pfad des neuesten Bildes zurück, falls es jung genug ist."""
    try:
        if not INBOX_DIR.is_dir():
            return None
        imgs = [
            f for f in INBOX_DIR.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        ]
    except OSError:
        return None

    if not imgs:
        return None

    newest = max(imgs, key=lambda f: f.stat().st_mtime)
    if time.time() - newest.stat().st_mtime > INBOX_MAX_AGE:
        return None
    return str(newest)


def _escape_path(path: str) -> str:
    """Leerzeichen escapen, damit der Pfad als ein Stück erkannt wird."""
    return path.replace(" ", "\\ ")


def _no_image_hint() -> str:
    return (
        f"⚠️  Kein aktuelles Bild in {INBOX_DIR} "
        f"(jünger als {INBOX_MAX_AGE // 60} Min.)"
    )


# ── ⌨️ Tastenbelegung ──────────────────────────────────────
kb = KeyBindings()


@kb.add("enter")
def _submit(event):
    event.current_buffer.validate_and_handle()


@kb.add("escape", "enter")   # Option+Enter
@kb.add("c-j")               # Ctrl+J (geht immer)
def _newline(event):
    event.current_buffer.insert_text("\n")


@kb.add("c-v")               # Wird von manchen Terminals abgefangen
@kb.add("c-t")               # Alternative, kommt praktisch immer an
def _paste_image(event):
    path = _latest_inbox_image()
    if path:
        event.current_buffer.insert_text(f" {_escape_path(path)} ")
    else:
        run_in_terminal(lambda: print(_no_image_hint()))


def _toolbar():
    return HTML(
        " <b>Enter</b> senden · <b>⌥+Enter</b>/<b>Ctrl+J</b> neue Zeile · "
        "<b>Ctrl+T</b>/<b>@shot</b> letzter Screenshot · "
        "<b>Ctrl+X Ctrl+E</b> Editor"
    )


_session: PromptSession | None = None


def _get_session() -> PromptSession:
    """Wird erst beim ersten Aufruf erstellt, damit der Import ohne TTY nicht abstürzt."""
    global _session
    if _session is None:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _session = PromptSession(
            history=FileHistory(str(HISTORY_FILE)),
            key_bindings=kb,
            multiline=True,
            enable_open_in_editor=True,
            bottom_toolbar=_toolbar,
            prompt_continuation=lambda width, line_no, wrap: "  ",
        )
    return _session


# ── 🔍 Bildpfade im Text finden ────────────────────────────
_PATH_RE = re.compile(
    r"'([^']+)'"                     # 'pfad mit leerzeichen.png'
    r'|"([^"]+)"'                    # "pfad.png"
    r"|((?:~|/)(?:\\.|[^\s\\])+)"    # /Users/du/Bild\ 1.png (Drag & Drop)
)


def extract_images(text: str) -> tuple[list[str], list[str]]:
    """
    Gibt (gefundene_bilder, fehlende_pfade) zurück.
    Robust gegen eingefügten Code, Logs und Stacktraces:
    Nicht-Bildpfade werden übersprungen, Fehler werden abgefangen.
    """
    found, missing = [], []

    for m in _PATH_RE.finditer(text):
        raw = next((g for g in m.groups() if g), None)
        if not raw or len(raw) > MAX_PATH_LEN or "\n" in raw:
            continue

        cleaned = re.sub(r"\\(.)", r"\1", raw).strip()

        # 1️⃣ Zuerst die Endung prüfen: nur Bilddateien sind interessant
        if Path(cleaned).suffix.lower() not in IMAGE_EXTS:
            continue

        # 2️⃣ ~ nur auflösen, wenn es sicher geht
        try:
            p = Path(cleaned).expanduser()
        except (RuntimeError, KeyError):
            missing.append(cleaned)
            continue

        # 3️⃣ Existiert die Datei im Container?
        try:
            exists = p.is_file()
        except OSError:          # z. B. Name zu lang
            exists = False

        if exists:
            if str(p) not in found:
                found.append(str(p))
        elif str(p) not in missing:
            missing.append(str(p))

    return found, missing


# ── 🖼️ @shot-Platzhalter ersetzen ─────────────────────────
def _replace_shot_placeholder(text: str) -> str:
    if SHOT_PLACEHOLDER not in text:
        return text

    path = _latest_inbox_image()
    if path:
        console.print(f"[green]🖼️  Screenshot eingefügt:[/green] {escape(path)}")
        return text.replace(SHOT_PLACEHOLDER, f" {_escape_path(path)} ")

    console.print(f"[yellow]{escape(_no_image_hint())}[/yellow]")
    return text


# ── 🎯 Öffentliche Funktion ────────────────────────────────
def read_instruction(question: str = "🎯 Was soll als nächstes gemacht werden?"):
    """Gibt (text, [bildpfade]) zurück."""
    text = _get_session().prompt(
        HTML(f"<b><ansiyellow>{question}</ansiyellow></b>\n› ")
    )

    text = _replace_shot_placeholder(text)

    try:
        images, missing = extract_images(text)
    except Exception as e:                       # Sicherheitsnetz: Eingabe nie verlieren
        console.print(f"[yellow]⚠️  Bilderkennung übersprungen: {escape(str(e))}[/yellow]")
        images, missing = [], []

    for p in missing:
        console.print(
            f"[yellow]⚠️  Bild im Container nicht gefunden:[/yellow] {escape(p)}\n"
            f"   [dim]→ Ist der Ordner als Volume gemountet (gleicher Pfad)?[/dim]"
        )
    if images:
        console.print(f"[green]✅ {len(images)} Bild(er) erkannt[/green]")

    return text.strip(), images


# ── 🖼️ Für das LLM: Bild → Content-Block ───────────────────
def image_to_content_block(path: str) -> dict:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
