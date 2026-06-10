# tools/github_tools.py

import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from github import Github, Auth
from config.settings import settings
import httpx

# ── GitHub API Setup ──
g = Github(auth=Auth.Token(settings.github_token))
repo = g.get_repo(settings.github_repo)

GRAPHQL_URL = "https://api.github.com/graphql"
GRAPHQL_HEADERS = {"Authorization": f"Bearer {settings.github_token}"}

# ── Project Board aktiv? ──
PROJECT_ENABLED = settings.github_project_number > 0


# ============================================================
# 🔑 Project ID
# ============================================================

_project_id_cache: str | None = None


def get_project_id() -> str | None:
    """Holt die GitHub Project v2 Node-ID (gecacht). Returns None wenn deaktiviert."""
    if not PROJECT_ENABLED:
        return None

    global _project_id_cache
    if _project_id_cache:
        return _project_id_cache

    owner = settings.github_repo.split("/")[0]

    for entity_type in ["user", "organization"]:
        query = f"""
        query($owner: String!, $number: Int!) {{
            {entity_type}(login: $owner) {{
                projectV2(number: $number) {{ id }}
            }}
        }}
        """
        resp = httpx.post(GRAPHQL_URL, json={
            "query": query,
            "variables": {
                "owner": owner,
                "number": settings.github_project_number,
            }
        }, headers=GRAPHQL_HEADERS)

        data = resp.json()
        try:
            _project_id_cache = data["data"][entity_type]["projectV2"]["id"]
            return _project_id_cache
        except (KeyError, TypeError):
            continue

    print(
        f"  ⚠️ Project #{settings.github_project_number} nicht gefunden für '{owner}' – wird übersprungen"
    )
    return None


# ============================================================
# 📊 Project Status & Fields
# ============================================================

_status_field_cache = None
_status_options_cache = None


def get_project_fields() -> tuple[str, dict] | tuple[None, None]:
    """Holt die Status-Feld-ID und alle Status-Optionen."""
    if not PROJECT_ENABLED:
        return None, None

    global _status_field_cache, _status_options_cache
    if _status_field_cache and _status_options_cache:
        return _status_field_cache, _status_options_cache

    project_id = get_project_id()
    if not project_id:
        return None, None

    query = """
    query($projectId: ID!) {
        node(id: $projectId) {
            ... on ProjectV2 {
                fields(first: 20) {
                    nodes {
                        ... on ProjectV2SingleSelectField {
                            id
                            name
                            options { id name }
                        }
                    }
                }
            }
        }
    }
    """
    resp = httpx.post(GRAPHQL_URL, json={
        "query": query,
        "variables": {"projectId": project_id}
    }, headers=GRAPHQL_HEADERS)

    data = resp.json()
    fields = data.get("data", {}).get("node", {}).get("fields", {}).get("nodes", [])

    for field in fields:
        if field.get("name") == "Status":
            _status_field_cache = field["id"]
            _status_options_cache = {
                opt["name"]: opt["id"] for opt in field.get("options", [])
            }
            print(f"  📋 Status-Optionen: {list(_status_options_cache.keys())}")
            return _status_field_cache, _status_options_cache

    print("  ⚠️ Status-Feld nicht im Project gefunden – wird übersprungen")
    return None, None


def set_project_item_status(item_id: str, status: str):
    """Setzt den Status eines Project Items."""
    if not PROJECT_ENABLED or not item_id:
        return None

    try:
        field_id, options = get_project_fields()
    except ValueError as e:
        print(f"  ⚠️ {e}")
        return None

    if not field_id or not options:
        return None

    if status not in options:
        print(f"  ⚠️ Status '{status}' nicht verfügbar. Optionen: {list(options.keys())}")
        return None

    query = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
        updateProjectV2ItemFieldValue(input: {
            projectId: $projectId
            itemId: $itemId
            fieldId: $fieldId
            value: { singleSelectOptionId: $optionId }
        }) { projectV2Item { id } }
    }
    """
    resp = httpx.post(GRAPHQL_URL, json={
        "query": query,
        "variables": {
            "projectId": get_project_id(),
            "itemId": item_id,
            "fieldId": field_id,
            "optionId": options[status],
        }
    }, headers=GRAPHQL_HEADERS)

    print(f"  📊 Status → {status}")
    return resp.json()


# ============================================================
# 📋 Issues
# ============================================================

def create_issue_with_assignee(title: str, body: str, assignee: str = None) -> dict:
    """Erstellt ein GitHub Issue mit Assignee + fügt es optional zum Project hinzu."""
    issue = repo.create_issue(
        title=title,
        body=body,
        assignees=[assignee] if assignee else [],
    )
    print(f"  👤 Issue #{issue.number} erstellt, Assignee: {assignee or 'keiner'}")

    # Issue zum Project hinzufügen (nur wenn Project aktiv)
    item_id = None
    project_id = get_project_id()

    if project_id:
        query = """
        mutation($projectId: ID!, $contentId: ID!) {
            addProjectV2ItemByContentId(input: {
                projectId: $projectId
                contentId: $contentId
            }) { item { id } }
        }
        """
        resp = httpx.post(GRAPHQL_URL, json={
            "query": query,
            "variables": {
                "projectId": project_id,
                "contentId": issue.node_id,
            }
        }, headers=GRAPHQL_HEADERS)

        data = resp.json()
        item_id = (
            data.get("data", {})
            .get("addProjectV2ItemByContentId", {})
            .get("item", {})
            .get("id")
        )

    return {
        "issue_number": issue.number,
        "number": issue.number,
        "issue_url": issue.html_url,
        "project_item_id": item_id,
    }


def close_issue(issue_number: int):
    """Schliesst ein GitHub Issue."""
    issue = repo.get_issue(number=issue_number)
    issue.edit(state="closed")
    print(f"  ✅ Issue #{issue_number} geschlossen")


def assign_issue_to(issue_number: int, username: str):
    """Weist ein GitHub Issue einem User zu."""
    try:
        issue = repo.get_issue(number=issue_number)
        issue.add_to_assignees(username)
        print(f"  👤 Issue #{issue_number} → {username} zugewiesen")
    except Exception as e:
        print(f"  ⚠️ Konnte Issue #{issue_number} nicht zuweisen: {e}")


def add_issue_comment(issue_number: int, body: str):
    """Fügt einen Kommentar zu einem GitHub Issue hinzu."""
    try:
        issue = repo.get_issue(number=issue_number)
        comment = issue.create_comment(body)
        print(f"  💬 Kommentar zu Issue #{issue_number} hinzugefügt")
        return comment.id
    except Exception as e:
        print(f"  ⚠️ Konnte Kommentar nicht erstellen: {e}")
        return None


# ============================================================
# 🌿 Branches
# ============================================================

def create_feature_branch(feature_name: str) -> str:
    """Erstellt feature/<name> Branch vom Base Branch (remote + lokal auschecken)."""
    base = repo.get_branch(settings.default_base_branch)
    ref_name = f"refs/heads/feature/{feature_name}"
    branch_name = f"feature/{feature_name}"

    try:
        repo.create_git_ref(ref=ref_name, sha=base.commit.sha)
        print(f"  🌿 Branch erstellt: {branch_name}")
    except Exception as e:
        if "already exists" in str(e):
            print(f"  🌿 Branch existiert bereits: {branch_name}")
        else:
            raise

    # ── Lokal auschecken (damit Developer auf dem richtigen Branch schreibt) ──
    git_local("fetch origin")
    current = git_local("branch --show-current").strip()
    if current != branch_name:
        output = git_local(f"checkout {branch_name}")
        if "error" in output.lower():
            git_local(f"checkout -b {branch_name} origin/{branch_name}")
        print(f"  🌿 Lokal auf Branch: {branch_name}")

    return branch_name


# ============================================================
# 🔀 Pull Requests
# ============================================================

def create_pull_request(
    branch: str,
    title: str,
    body: str,
    issue_number: int = None,
) -> str:
    """Erstellt Draft PR → Base Branch mit optionalem auto-close Link."""
    if issue_number:
        body += f"\n\nCloses #{issue_number}"

    try:
        pr = repo.create_pull(
            title=title,
            body=body,
            head=branch,
            base=settings.default_base_branch,
            draft=True,
        )
        print(f"  🔀 PR erstellt: {pr.html_url}")
        return pr.html_url
    except Exception as e:
        if "No commits between" in str(e):
            print(f"  ⚠️ Keine Commits zwischen {settings.default_base_branch} und {branch} – PR übersprungen")
            return "n/a (keine Änderungen)"
        elif "A pull request already exists" in str(e):
            print(f"  ⚠️ PR existiert bereits für {branch}")
            return "n/a (PR existiert bereits)"
        else:
            raise


# ============================================================
# 🖥️ Lokale Git-Befehle (im Projekt)
# ============================================================

def git_local(command: str) -> str:
    """Führt lokale git Befehle im Projekt-Repo aus."""
    result = subprocess.run(
        f"git {command}",
        shell=True,
        cwd=settings.repo_path,
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


def get_current_branch() -> str:
    """Gibt den aktuellen lokalen Branch zurück."""
    return git_local("branch --show-current").strip()


def checkout_branch(branch_name: str) -> str:
    """Wechselt lokal auf einen Branch (fetch + checkout)."""
    git_local("fetch origin")
    output = git_local(f"checkout {branch_name}")
    if "error" in output.lower():
        output = git_local(f"checkout -b {branch_name} origin/{branch_name}")
    print(f"  🌿 Auf Branch: {branch_name}")
    return output


def ensure_on_branch(branch_name: str) -> str:
    """
    Stellt sicher dass wir auf dem richtigen Branch sind.
    OHNE fetch – damit lokale Änderungen nicht verloren gehen.
    """
    current = get_current_branch()
    if current == branch_name:
        return f"Bereits auf {branch_name}"

    # Nur lokaler checkout (kein fetch, keine Remote-Überschreibung)
    output = git_local(f"checkout {branch_name}")
    if "error" in output.lower():
        # Branch existiert lokal noch nicht → von remote holen
        git_local("fetch origin")
        output = git_local(f"checkout -b {branch_name} origin/{branch_name}")
    print(f"  🌿 Auf Branch: {branch_name}")
    return output


def commit_and_push(files: list[str], message: str, branch_name: str) -> str:
    """
    Staged, committed und pusht Dateien auf den Feature-Branch.
    WICHTIG: Macht KEINEN destructiven checkout – lokale Änderungen bleiben erhalten.
    """

    # ── Sicherstellen dass wir auf dem richtigen Branch sind (ohne fetch!) ──
    ensure_on_branch(branch_name)

    # ── Stage alle Änderungen ──
    git_local("add -A")

    # ── Prüfe ob es etwas zu committen gibt ──
    status = git_local("status --porcelain")
    if not status.strip():
        print(f"  ⚠️ Keine Änderungen zu committen auf {branch_name}")

        # Debug: Zeige was auf dem Branch ist vs. remote
        diff_info = git_local(f"log origin/{settings.default_base_branch}..HEAD --oneline")
        if diff_info.strip():
            print(f"  ℹ️ Lokale Commits vorhanden (noch nicht gepusht?):")
            for line in diff_info.strip().split("\n")[:5]:
                print(f"     {line}")
            # Push versuchen falls lokale Commits vorhanden
            push_output = git_local(f"push origin {branch_name}")
            if "Everything up-to-date" not in push_output:
                print(f"  📦 Nachträglicher Push erfolgreich")
                return push_output
        return "nothing to commit"

    # ── Commit ──
    commit_output = git_local(f'commit -m "{message}"')
    if "nothing to commit" in commit_output:
        print(f"  ⚠️ Git sagt: nothing to commit")
        return "nothing to commit"
    print(f"  📝 Commit: {message}")

    # ── Push ──
    push_output = git_local(f"push origin {branch_name}")
    print(f"  📦 Push: {message} ({len(files)} Dateien)")

    # ── Push validieren ──
    if "Everything up-to-date" in push_output:
        print(f"  ⚠️ Push: Everything up-to-date – versuche force push")
        push_output = git_local(f"push origin {branch_name} --force")

    if "rejected" in push_output.lower():
        print(f"  ⚠️ Push rejected – versuche force push")
        push_output = git_local(f"push origin {branch_name} --force")

    if "error" in push_output.lower() and "force" not in push_output.lower():
        print(f"  ❌ Push Fehler: {push_output[-300:]}")

    # ── Verifiziere: Diff zum Base Branch vorhanden? ──
    git_local("fetch origin")
    diff_check = git_local(f"log origin/{settings.default_base_branch}..origin/{branch_name} --oneline")
    if not diff_check.strip():
        print(f"  ⚠️ WARNUNG: Kein Diff auf Remote zwischen {settings.default_base_branch} und {branch_name}")
        return "nothing to commit"

    commit_count = len(diff_check.strip().split("\n"))
    print(f"  ✅ {commit_count} Commit(s) auf Remote verifiziert")
    return push_output


# ============================================================
# 🔄 Task Lifecycle Workflows
# ============================================================

def create_task_workflow(task_id: str, task_title: str, task_body: str) -> dict:
    """
    Kompletter Workflow: Branch + Issue + optional Status setzen.
    Branch wird sofort lokal ausgecheckt damit der Developer darauf arbeitet.
    """
    # 1. Feature Branch erstellen + lokal auschecken
    branch_name = create_feature_branch(task_id)

    # 2. Issue mit Assignee erstellen + optional zum Project hinzufügen
    assignee = settings.github_repo.split("/")[0]
    issue_data = create_issue_with_assignee(
        title=task_title,
        body=task_body,
        assignee=assignee,
    )

    # 3. Status auf "Todo" (nur wenn Project aktiv)
    if issue_data.get("project_item_id"):
        set_project_item_status(issue_data["project_item_id"], "Todo")

    print(f"  ✅ Task erstellt: {task_title}")
    print(f"  🌿 Branch: {branch_name}")
    print(f"  📋 Issue: {issue_data.get('issue_url', '?')}")

    return {
        "branch_name": branch_name,
        "issue_data": issue_data,
    }


def start_task(task: dict) -> str:
    """Startet einen Task: Status → In Progress + Branch auschecken."""
    item_id = task.get("issue_data", {}).get("project_item_id")
    if item_id:
        set_project_item_status(item_id, "In Progress")

    branch_name = task.get("branch_name", "")
    if branch_name:
        ensure_on_branch(branch_name)

    print(f"  🚀 Task gestartet: {branch_name}")
    return branch_name


def complete_task(
    task: dict,
    files: list[str],
    commit_msg: str,
) -> dict:
    """
    Schliesst einen Task ab:
    1. Commit + Push
    2. Pull Request erstellen (auto-close Issue)
    3. Status → Done (nur wenn Project aktiv)
    """
    branch_name = task.get("branch_name", "")
    issue_data = task.get("issue_data", {})
    issue_number = issue_data.get("issue_number")

    # 1. Commit + Push
    push_result = commit_and_push(files, commit_msg, branch_name)

    # 2. PR erstellen (nur wenn Commits vorhanden)
    if push_result == "nothing to commit":
        print(f"  ⚠️ Keine Änderungen – PR wird übersprungen")
        pr_url = "n/a (keine Änderungen)"
    else:
        pr_url = create_pull_request(
            branch=branch_name,
            title=commit_msg,
            body=(
                f"## Änderungen\n"
                f"{commit_msg}\n\n"
                f"### Geänderte Dateien\n"
                + "\n".join(f"- `{f}`" for f in files)
            ),
            issue_number=issue_number,
        )

    # 3. Status → Done (nur wenn Project aktiv)
    item_id = issue_data.get("project_item_id")
    if item_id:
        set_project_item_status(item_id, "Done")

    print(f"  ✅ Task abgeschlossen!")
    print(f"  🔀 PR: {pr_url}")

    return {
        "branch_name": branch_name,
        "pr_url": pr_url,
        "issue_number": issue_number,
    }
