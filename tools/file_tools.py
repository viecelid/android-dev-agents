# tools/file_tools.py

import sys
import os
import subprocess
import stat
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.tools import tool
from config.settings import settings


# ============================================================
# ⚙️ Ignore-Patterns für Dateisuche
# ============================================================

IGNORE_DIRS = {
    ".git", ".idea", ".vscode",
    "build", ".gradle",
    "__pycache__", ".cache",
    "node_modules",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
    ".tflite", ".bin", ".so", ".jar", ".aar",
    ".zip", ".tar", ".gz",
    ".ttf", ".otf", ".woff", ".woff2",
    ".wav", ".mp3", ".ogg",
    ".db", ".sqlite",
    ".class", ".dex",
    ".keystore", ".jks",
    ".pdf", ".doc", ".docx",
}


# ============================================================
# 📂 Datei-Listing (generisch)
# ============================================================

def _list_files(base_path: str, extensions: list[str] = None) -> list[str]:
    """
    Listet alle Dateien in einem Verzeichnis.
    Optional gefiltert nach Extensions. Überspringt Binärdateien.
    """
    files = []
    if not os.path.exists(base_path):
        return files
    for root, dirs, filenames in os.walk(base_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in filenames:
            # Binärdateien überspringen
            ext = os.path.splitext(f)[1].lower()
            if ext in BINARY_EXTENSIONS:
                continue
            rel_path = os.path.relpath(
                os.path.join(root, f), base_path
            )
            if extensions:
                if any(f.endswith(e) for e in extensions):
                    files.append(rel_path)
            else:
                files.append(rel_path)
    return files


# ============================================================
# 🧹 Unicode-Bereinigung
# ============================================================

def _sanitize_content(content: str) -> str:
    """Entfernt ungültige Unicode-Zeichen (Surrogates) die API-Calls crashen."""
    return content.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")


# ============================================================
# 📖 Datei-Operationen (einzelnes Repo)
# ============================================================

def read_file(filepath: str) -> str | None:
    """Liest eine Text-Datei aus dem Projekt."""
    try:
        full_path = os.path.join(settings.repo_path, filepath)
        with open(full_path, "rb") as f:
            raw = f.read()
        # Decode mit Surrogate-Handling und sofort bereinigen
        content = raw.decode("utf-8", errors="surrogateescape")
        content = _sanitize_content(content)
        return content
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"  ⚠️ Fehler beim Lesen von {filepath}: {e}")
        return None


def write_file(filepath: str, content: str) -> str:
    """Schreibt/erstellt eine Datei im Projekt."""
    full_path = os.path.join(settings.repo_path, filepath)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def delete_file(filepath: str) -> str:
    """Löscht eine Datei aus dem Projekt und räumt leere Verzeichnisse auf."""
    full_path = os.path.join(settings.repo_path, filepath)
    if not os.path.exists(full_path):
        print(f"  ⚠️ Datei nicht gefunden: {filepath}")
        return f"⚠️ Not found: {filepath}"
    os.remove(full_path)
    print(f"  🗑️ Deleted: {filepath}")

    # Leere Verzeichnisse aufräumen (von unten nach oben)
    dir_path = os.path.dirname(full_path)
    while dir_path != settings.repo_path and dir_path.startswith(settings.repo_path):
        if os.path.isdir(dir_path) and not os.listdir(dir_path):
            os.rmdir(dir_path)
            rel_dir = os.path.relpath(dir_path, settings.repo_path)
            print(f"  🗑️ Leeres Verzeichnis entfernt: {rel_dir}")
            dir_path = os.path.dirname(dir_path)
        else:
            break

    return f"✅ Deleted: {filepath}"


def rename_file(old_path: str, new_path: str) -> str:
    """Benennt eine Datei im Projekt um."""
    full_old = os.path.join(settings.repo_path, old_path)
    full_new = os.path.join(settings.repo_path, new_path)
    if not os.path.exists(full_old):
        print(f"  ⚠️ Datei nicht gefunden: {old_path}")
        return f"⚠️ Not found: {old_path}"
    os.makedirs(os.path.dirname(full_new), exist_ok=True)
    os.rename(full_old, full_new)
    print(f"  📝 Renamed: {old_path} → {new_path}")
    return f"✅ Renamed: {old_path} → {new_path}"


# ============================================================
# 📂 Projekt-Übersicht
# ============================================================

def get_file_tree(extensions: list[str] = None) -> list[str]:
    """Listet alle relevanten Dateien im Projekt."""
    if extensions is None:
        extensions = settings.file_extensions
    return _list_files(settings.repo_path, extensions)


def read_all_files(extensions: list[str] = None) -> dict[str, str]:
    """Liest alle relevanten Dateien → {pfad: inhalt}."""
    files = get_file_tree(extensions)
    result = {}
    for f in files:
        content = read_file(f)
        if content:
            result[f] = content
    return result


# ============================================================
# 📦 Generierter Code schreiben
# ============================================================

def write_generated_code(code_dict: dict[str, str]) -> list[str]:
    """Schreibt alle generierten Dateien ins Projekt."""
    written = []
    for filepath, content in code_dict.items():
        write_file(filepath, content)
        written.append(filepath)
        print(f"  📄 Geschrieben: {filepath}")
    return written


# ============================================================
# 🔨 Build
# ============================================================

@tool
def run_build(command: str = "") -> str:
    """Führt einen Build-Befehl im Projekt aus."""
    build_cmd = command or settings.build_command
    cmd_parts = build_cmd.split()

    # Gradle Wrapper executable machen
    _prepare_build_environment(cmd_parts[0])

    try:
        result = subprocess.run(
            cmd_parts,
            cwd=settings.repo_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return (
            f"EXIT: {result.returncode}\n"
            f"STDOUT: {result.stdout[-2000:]}\n"
            f"STDERR: {result.stderr[-2000:]}"
        )
    except subprocess.TimeoutExpired:
        return "EXIT: -1\nSTDERR: Build timeout expired!"
    except FileNotFoundError as e:
        return f"EXIT: -1\nSTDERR: Build command not found: {e}"
    except Exception as e:
        return f"EXIT: -1\nSTDERR: Build error: {e}"


def _prepare_build_environment(executable: str):
    """Macht Build-Scripts executable (Gradle Wrapper, Maven Wrapper)."""
    wrappers = {
        "./gradlew": "gradlew",
        "gradlew": "gradlew",
        "./mvnw": "mvnw",
        "mvnw": "mvnw",
    }

    if executable in wrappers:
        wrapper_name = wrappers[executable]
        wrapper_path = os.path.join(settings.repo_path, wrapper_name)
        if os.path.exists(wrapper_path):
            st = os.stat(wrapper_path)
            os.chmod(
                wrapper_path,
                st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH,
            )


# ============================================================
# 🔍 Projekt-Status
# ============================================================

def is_project_initialized() -> bool:
    """Prüft ob das Projekt bereits aufgesetzt ist (Android Gradle Projekt)."""
    repo = settings.repo_path
    return (
        os.path.exists(os.path.join(repo, "build.gradle.kts"))
        and os.path.exists(os.path.join(repo, "app", "build.gradle.kts"))
        and os.path.exists(os.path.join(repo, "settings.gradle.kts"))
    )


# ============================================================
# 🔧 LANGCHAIN TOOLS – Vom Developer Agent nutzbar
# ============================================================

@tool
def read_file_tool(filepath: str) -> str:
    """
    Liest eine Text-Datei aus dem Projekt.
    Nutze dies um bestehenden Code zu lesen und zu verstehen.

    Args:
        filepath: Relativer Pfad im Projekt
                  z.B. "app/src/main/kotlin/ch/ffhs/mosquitobuzz/MainActivity.kt"
                  z.B. "app/build.gradle.kts"
                  z.B. "gradle/libs.versions.toml"
    """
    content = read_file(filepath)
    if content is None:
        return f"⚠️ Datei nicht gefunden: {filepath}"
    return content


@tool
def list_dir_tool(directory: str) -> str:
    """
    Listet alle Dateien in einem Verzeichnis des Projekts.
    Nutze dies um die Projekt-Struktur zu erkunden.

    Args:
        directory: Relativer Pfad zum Verzeichnis
                   z.B. "app/src/main/kotlin/ch/ffhs/mosquitobuzz"
                   z.B. "app/src/main/res"
                   z.B. "gradle"
    """
    base = os.path.join(settings.repo_path, directory)
    if not os.path.exists(base):
        return f"⚠️ Verzeichnis nicht gefunden: {directory}"

    files = _list_files(base)
    if not files:
        return f"Keine Dateien in {directory}"

    result = f"📂 {directory} ({len(files)} Dateien):\n"
    result += "\n".join(f"  • {f}" for f in sorted(files))
    return result


@tool
def list_files_tool(directory: str = "") -> str:
    """
    Listet alle Dateien im Projekt.
    Optional eingeschränkt auf ein Unterverzeichnis.

    Args:
        directory: Optionales Unterverzeichnis (leer = ganzes Projekt)
    """
    base = os.path.join(settings.repo_path, directory)
    if not os.path.exists(base):
        return f"⚠️ Verzeichnis nicht gefunden: {directory}"
    files = _list_files(base)
    if not files:
        return "Keine Dateien gefunden."
    return "\n".join(sorted(files))


@tool
def delete_file_tool(filepath: str) -> str:
    """
    Löscht eine Datei aus dem Projekt.
    Nutze dies um nicht mehr benötigte Dateien zu entfernen.

    Args:
        filepath: Relativer Pfad im Projekt
                  z.B. "app/src/main/kotlin/ch/dv/MobileAndroidTestApp/OldScreen.kt"
    """
    return delete_file(filepath)
