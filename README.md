# 🤖 Android Dev Agents (based on LangGraph)

An AI-powered multi-agent system that helps you develop Android apps iteratively through natural language instructions. Built with LangGraph, it orchestrates a team of specialized agents that plan, implement, test, and commit code — all with human-in-the-loop review at every step.

Author: Dario Vieceli


## 🧠 How It Works

You give instructions in plain language ("Add a login screen", "Implement dark mode", etc.) and the agent system takes over:

1. 🏗️ Planner/Architect → breaks your instruction into a task, defines architecture
2. 👤 You → review & approve the plan (or give feedback)
3. 💻 Developer → implements Kotlin code
4. 👤 You → review & approve the code (or give feedback)
5. 🧪 Tester → runs build, writes tests & docs
6. 👤 You → review & approve the result
7. 📦 Commit → pushes to GitHub, creates PR, closes issue
8. 🔁 Back to you → next instruction

Every step requires your explicit approval. You can provide feedback at any point and the agents will adjust.


## ✨ Features

- Interactive development loop — give instructions, review plans, approve code
- Automatic GitHub integration — branches, issues, PRs, project board updates
- Build verification — automated ./gradlew assembleDebug with retry logic
- Checkpoint & resume — pause anytime with Ctrl+C, continue where you left off
- Project scaffolding — start from scratch with a clean Hello World project
- Initial analysis — on first startup, the system analyzes and summarizes your existing project


## 📋 Prerequisites

- Python 3.11+
- Docker (recommended) or local Python environment
- GitHub account with a repository for your Android project
- API keys:
  - OpenRouter (https://openrouter.ai/) or any OpenAI-compatible API
  - Anthropic (https://console.anthropic.com/) — optional, depending on model choice
  - GitHub Personal Access Token (https://github.com/settings/tokens) with repo + project permissions


## 🚀 Setup (Local)

1. Clone this repository:

   git clone https://github.com/viecelid/android-dev-agents.git
   cd android-dev-agents

2. Create virtual environment:

   python -m venv .venv
   source .venv/bin/activate

3. Install dependencies:

   pip install -r requirements.txt

4. Configure environment:

   cp .env.example .env

   Edit .env with your values (see Configuration section below).

5. Run:

   python main.py


## 🐳 Setup (Docker) — Recommended

Running in Docker provides a clean, isolated environment and avoids dependency conflicts.

### Dockerfile

Create a Dockerfile in the project root:

   FROM python:3.12-slim

   WORKDIR /app/android-dev-agents

   RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt

   COPY . .

   CMD ["python", "main.py"]

### Build the image

   docker build -t android-dev-agents .

### Run interactively

   docker run -it \
     --name dev-agents \
     -v /path/to/your/android/project:/app/YourProject \
     -v $(pwd)/.env:/app/android-dev-agents/.env:ro \
     -v $(pwd)/checkpoints:/app/android-dev-agents/checkpoints \
     android-dev-agents

Flags explained:
- -it → interactive terminal (required for human review)
- -v .../project:/app/YourProject → mount your Android project
- -v .env:.../.env:ro → mount env file read-only (security)
- -v .../checkpoints:... → persist checkpoints between restarts

### Docker Compose (alternative)

Create docker-compose.yml:

   version: '3.8'
   services:
     dev-agents:
       build: .
       stdin_open: true
       tty: true
       volumes:
         - /path/to/your/android/project:/app/YourProject
         - ./.env:/app/android-dev-agents/.env:ro
         - ./checkpoints:/app/android-dev-agents/checkpoints
         - ./logs:/app/android-dev-agents/logs
         - ./documentation:/app/android-dev-agents/documentation

Run with:

   docker compose run dev-agents

### Security best practices for Docker

- Never bake API keys into the image — always mount .env at runtime
- Use :ro (read-only) for the .env mount
- Don't push the image to public registries
- Mount the Android project rather than copying it into the image
- Persist checkpoints via volume mount so you can resume after container restarts


## 🎮 Usage

### Start the agent system

   python main.py

### First run (existing project)

The system will:
1. Load and analyze your project
2. Show you a summary (structure, features, tech stack)
3. Wait for your first instruction

### First run (empty project)

The system will:
1. Detect that no project exists
2. Offer to scaffold a new Android project (Kotlin, Jetpack Compose, Material 3)
3. After scaffolding, wait for your instructions

### Giving instructions

   🎯 Was soll als nächstes gemacht werden? Add a settings screen with dark mode toggle

The Planner will create a task plan. Review it:

   👤 Dein Review (ok / Feedback): ok

Or give feedback:

   👤 Dein Review (ok / Feedback): Also add a language selector

### Commands

| Command          | Action                          |
|------------------|---------------------------------|
| ok / yes / ja    | Approve current step            |
| Any text         | Feedback → agent adjusts        |
| skip             | Skip current task               |
| status           | Show project status             |
| exit / quit      | Exit the loop                   |
| Ctrl+C           | Pause (checkpoint saved)        |

### Resume after pause

Simply run python main.py again. The system detects the checkpoint and asks if you want to continue.


## 📁 Project Structure

   android-dev-agents/
   ├── main.py                  # Entry point & interactive loop
   ├── graph.py                 # LangGraph workflow definition
   ├── state.py                 # Agent state model
   ├── config/
   │   └── settings.py          # Pydantic settings (from .env)
   ├── agents/
   │   ├── planner.py           # Planner/Architect agent
   │   ├── developer.py         # Developer agent
   │   └── tester.py            # Tester/QA agent
   ├── tools/
   │   ├── file_tools.py        # File operations + build
   │   └── github_tools.py      # GitHub API (issues, PRs, branches)
   ├── prompts/
   │   ├── planner_prompt.md    # System prompt for Planner
   │   ├── developer_prompt.md  # System prompt for Developer
   │   └── tester_prompt.md     # System prompt for Tester
   ├── checkpoints/             # SQLite checkpoints (auto-generated)
   ├── logs/                    # Build logs (auto-generated)
   └── documentation/           # Auto-generated dev docs


## ⚙️ Configuration

All configuration is done via environment variables (.env file).

| Variable              | Description                | Example                          |
|-----------------------|----------------------------|----------------------------------|
| ANTHROPIC_API_KEY     | Anthropic API key          | sk-ant-...                       |
| OPENAI_API_KEY        | OpenRouter API key         | sk-or-...                        |
| OPENAI_API_BASE       | API base URL               | https://openrouter.ai/api/v1     |
| GITHUB_TOKEN          | GitHub PAT                 | ghp_...                          |
| GITHUB_REPO           | Target repo                | user/repo                        |
| GITHUB_PROJECT_NUMBER | Project board number       | 1                                |
| DEFAULT_BASE_BRANCH   | Base branch for PRs        | main                             |
| REPO_PATH             | Path to Android project    | /app/MosquitoBuzzV5              |
| BUILD_COMMAND         | Build command              | ./gradlew assembleDebug          |
| APP_PACKAGE           | Android package name       | ch.ffhs.mosquitobuzz             |
| APP_NAME              | App display name           | MosquitoBuzz                     |
| ANDROID_MIN_SDK       | Minimum SDK                | 31                               |
| ANDROID_TARGET_SDK    | Target SDK                 | 35                               |
| ANDROID_COMPILE_SDK   | Compile SDK                | 36                               |
| MAX_RETRIES           | Max build retries          | 3                                |


## 🛠️ Tech Stack

| Component        | Technology                              |
|------------------|-----------------------------------------|
| Orchestration    | LangGraph                               |
| LLM              | OpenRouter (Qwen 3.5 397B) / any model  |
| Structured Output| Pydantic + LangChain                    |
| Checkpointing    | SQLite                                  |
| GitHub           | PyGithub + GraphQL API                  |
| Terminal UI      | Rich                                    |
| Config           | Pydantic Settings + dotenv              |


## 🧪 Android Tech Stack (Generated Projects)

The agents generate code following these conventions:

- Kotlin with modern idioms
- Jetpack Compose + Material 3 (no XML layouts)
- MVVM + Clean Architecture
- Hilt for DI (via KSP)
- Coroutines + StateFlow for async & state
- Repository Pattern for data access


## 📝 License

MIT License — see LICENSE file for details.
