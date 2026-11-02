# 🤖 Android Dev Agents

Build Android apps from plain-language instructions. A LangGraph multi-agent system plans, codes, tests and commits. You approve every step.

**Author:** Dario Vieceli

---

## 🧠 How It Works

```
You → 🏗️ Planner → 👤 Review → 💻 Developer → 👤 Review → 🧪 Tester → 👤 Review → 📦 Commit & PR
```

1. **Planner** turns your instruction (and screenshots) into tasks and sets the architecture
2. **Developer** writes the Kotlin code
3. **Tester** runs the build and writes tests and docs
4. **Commit** pushes the code, opens a PR and closes the issue

At every review you can reply `ok` or give feedback. The agents adapt to your feedback.

---

## ✨ Features

- 💬 Natural-language development loop
- 🖼️ Screenshots as input: show the Planner what you want
- ⌨️ Multi-line input with paste support
- 🐙 GitHub integration: branches, issues, PRs, project board
- 🔨 Build check with automatic retries
- 💾 Checkpoints: pause with `Ctrl+C`, resume later
- 🆕 Creates a new project if none exists (Compose + Material 3)

---

## 📋 Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- A GitHub repo for your Android project, plus the [GitHub CLI](https://cli.github.com/) (authenticated)
- API keys: [OpenRouter](https://openrouter.ai/) (or any OpenAI-compatible API) and a GitHub PAT with `repo` + `project` scopes
- For screenshots: a model that accepts image input

---

## 🚀 Quick Start

### 1. Clone & build

```bash
git clone https://github.com/viecelid/android-dev-agents.git
cd ..   # build from the PARENT folder
docker build --platform linux/amd64 -t android-dev-agents \
  -f android-dev-agents/exampleDocker/DockerImageAndroidDevAgents .
```

### 2. Configure `.env.docker`

Use the paths **inside the container**:

```env
OPENAI_API_KEY=sk-or-...
OPENAI_API_BASE=https://openrouter.ai/api/v1
ANTHROPIC_API_KEY=sk-ant-...

GITHUB_TOKEN=ghp_...
GITHUB_REPO=youruser/YourApp
GITHUB_PROJECT_NUMBER=1        # 0 = disable project board
DEFAULT_BASE_BRANCH=main       # must exist on GitHub

REPO_PATH=/app/YourProject
BUILD_COMMAND=./gradlew assembleDebug

APP_PACKAGE=com.example.myapp
APP_NAME=MyApp

IMAGE_INBOX=/inbox             # optional, folder for screenshots
IMAGE_INBOX_MAX_AGE=600        # optional, max image age in seconds
```

### 3. Run

```bash
docker run -it --platform linux/amd64 \
  -v /path/to/android-dev-agents:/app/android-dev-agents \
  -v /path/to/YourProject:/app/YourProject \
  -v /path/to/screenshots:/inbox \
  -v ~/.config/gh:/root/.config/gh:ro \
  --env-file /path/to/android-dev-agents/.env.docker \
  -w /app/android-dev-agents \
  android-dev-agents \
  bash -c '
    export GIT_CONFIG_GLOBAL=/tmp/.gitconfig
    git config --global url."https://${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/"
    git config --global user.name "youruser"
    git config --global user.email "you@example.com"
    exec bash'
```

Inside the container:

```bash
python main.py
```

---

## 🎮 Commands

| Input               | Action                   |
|---------------------|--------------------------|
| `ok` / `yes` / `ja` | Approve                  |
| any text            | Send feedback            |
| `skip`              | Skip the current task    |
| `status`            | Show project status      |
| `exit` / `quit`     | Quit                     |
| `Ctrl+C`            | Pause (checkpoint saved) |

## ⌨️ Input

| Key / Text               | Action                                  |
|--------------------------|-----------------------------------------|
| `Enter`                  | Send                                    |
| `Option+Enter` / `Ctrl+J`| New line                                |
| `Ctrl+T`                 | Insert the latest screenshot from inbox |
| `@shot`                  | Replaced by the latest screenshot       |
| Drag & drop              | Image path (folder must be mounted)     |
| `Ctrl+X Ctrl+E`          | Open input in `$EDITOR`                 |

> 💡 Save your screenshot to the mounted inbox folder, then type `@shot` in your instruction.

---

## 📁 Structure

```
android-dev-agents/
├── main.py          # Entry point & loop
├── graph.py         # LangGraph workflow
├── state.py         # Agent state
├── agents/          # Planner, Developer, Tester
├── tools/           # File, build & GitHub tools
├── prompts/         # System prompts
├── config/          # Settings (.env)
├── utils/           # Terminal input & LLM helpers
└── exampleDocker/   # Dockerfile
```

---

## 🛠️ Tech Stack

**Agents:** LangGraph · LangChain · Pydantic · SQLite · PyGithub · Rich · prompt_toolkit
**Generated apps:** Kotlin · Jetpack Compose · Material 3 · MVVM · Hilt (KSP) · Coroutines + StateFlow

---

## 🔒 Security

- Pass API keys in at runtime with `--env-file`. Never put them in the image.
- Mount sensitive config read-only (`:ro`).
- Don't push the image to public registries.

---

## 📝 License

MIT
