# 🤖 Android Dev Agents

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

- macOS (this guide is written for macOS)
- Docker Desktop for Mac (https://www.docker.com/products/docker-desktop/)
- GitHub account with a repository for your Android project
- GitHub CLI (gh) authenticated locally (https://cli.github.com/)
- API keys:
  - OpenRouter (https://openrouter.ai/) or any OpenAI-compatible API
  - Anthropic (https://console.anthropic.com/) — optional, depending on model choice
  - GitHub Personal Access Token (https://github.com/settings/tokens) with repo + project permissions


## 🐳 Setup (Docker on macOS)

This project is designed to run inside a Docker container. The container includes Python, the Android SDK, Git, and all dependencies needed to build Android projects and run the agents.

### 1. Install Docker Desktop

Download and install Docker Desktop for Mac from:
https://www.docker.com/products/docker-desktop/

Make sure Docker Desktop is running (whale icon visible in menu bar).

### 2. Clone the repository

   git clone https://github.com/viecelid/android-dev-agents.git

The folder must be called android-dev-agents. If you rename it, you must update
all paths in the docker commands and the Dockerfile accordingly.

### 3. Build the Docker image

Navigate to the PARENT directory of android-dev-agents and build from there:

   cd /path/to/parent-folder
   docker build --platform linux/amd64 -t android-dev-agents -f android-dev-agents/exampleDocker/DockerImageAndroidDevAgents .

The build context (.) is the parent folder. This is required because the Dockerfile
references files via the android-dev-agents/ prefix.

Note: --platform linux/amd64 is required on Apple Silicon Macs (M1/M2/M3/M4).
The build may take several minutes on first run (downloading Android SDK, etc.).

Example folder structure:

   parent-folder/              <-- run docker build HERE
   ├── android-dev-agents/    <-- the cloned repo
   │   ├── exampleDocker/
   │   │   └── DockerImageAndroidDevAgents
   │   ├── requirements.txt
   │   ├── main.py
   │   └── ...
   └── YourAndroidProject/    <-- your Android project (optional, can be anywhere)

### 4. Configure environment (.env.docker)

You need a .env.docker file that contains the environment variables with paths
as they appear INSIDE the container (not your local macOS paths).

Create or edit .env.docker in the android-dev-agents folder:

   # LLM API Keys
   ANTHROPIC_API_KEY=sk-ant-...
   OPENAI_API_KEY=sk-or-...
   OPENAI_API_BASE=https://openrouter.ai/api/v1

   # GitHub
   GITHUB_TOKEN=ghp_...
   GITHUB_REPO=youruser/YourApp
   GITHUB_PROJECT_NUMBER=1
   DEFAULT_BASE_BRANCH=main

   # Project (path INSIDE the container — not your macOS path!)
   REPO_PATH=/app/YourProject

   # Build
   BUILD_COMMAND=./gradlew assembleDebug

   # Android App
   APP_PACKAGE=com.example.myapp
   APP_NAME=MyApp
   ANDROID_MIN_SDK=31
   ANDROID_TARGET_SDK=35
   ANDROID_COMPILE_SDK=36

   # Agent
   MAX_RETRIES=3

Important: The DEFAULT_BASE_BRANCH must already exist on your GitHub repository.
For new/empty repos this is typically "main". If you set it to something like
"developer", make sure that branch exists on GitHub first:

   cd /path/to/your/android/project
   git checkout -b developer
   git push origin developer

If the branch doesn't exist, you'll get a "Branch not found: 404" error when
the agent tries to create feature branches.

Why .env.docker?

Your local .env uses macOS paths like /Users/dario/StudioProjects/MosquitoBuzzV5.
Inside the container, the project is mounted at /app/YourProject instead.
The .env.docker file uses container-internal paths so the agents can find your project.

| File         | Used by          | Paths                              |
|--------------|------------------|------------------------------------|
| .env         | Local dev        | /Users/you/StudioProjects/...      |
| .env.docker  | Docker container | /app/... (container mount points)  |

### 5. Run the container

   docker run -it --platform linux/amd64 \
     -v /path/to/android-dev-agents:/app/android-dev-agents \
     -v /path/to/your/android/project:/app/YourProject \
     -v ~/.config/gh:/root/.config/gh:ro \
     --env-file /path/to/android-dev-agents/.env.docker \
     -w /app/android-dev-agents \
     android-dev-agents \
     bash -c '
       export GIT_CONFIG_GLOBAL=/tmp/.gitconfig
       git config --global url."https://${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/"
       git config --global user.name "youruser"
       git config --global user.email "your-email@example.com"
       exec bash'

Replace the paths:
- /path/to/android-dev-agents → your local clone of this repo
- /path/to/your/android/project → your Android project on your Mac

Flags and mounts explained:
- -it → interactive terminal (required for human review input)
- --platform linux/amd64 → required for Apple Silicon Macs (M1/M2/M3/M4)
- -v .../android-dev-agents:/app/android-dev-agents → mounts the agent repo (live code changes)
- -v .../YourProject:/app/YourProject → mounts your Android project
- -v ~/.config/gh:/root/.config/gh:ro → shares GitHub CLI auth (read-only)
- --env-file .env.docker → injects environment variables with container paths
- -w /app/android-dev-agents → sets working directory inside container
- bash -c '...' → configures git credentials using the GITHUB_TOKEN from .env.docker

After the container starts, you are in a bash shell. Start the agents with:

   python main.py

### 6. Restart after stopping

If the container was stopped but still exists:

   docker start -i <container-name>

If you want a fresh start (removes container):

   docker rm <container-name>

Then run the docker run command from step 5 again.

### Security best practices

- Never bake API keys into the Docker image — always inject via --env-file at runtime
- Use :ro (read-only) for sensitive mounts like GitHub CLI config
- Don't push the image to public registries
- Mount the Android project rather than copying it into the image
- Rotate API keys if they were ever accidentally committed to Git


## 🎮 Usage

### Start the agent system

Once inside the container, start the agents:

   python main.py

On first run with an existing project:
1. The system loads and analyzes your project
2. Shows you a summary (structure, features, tech stack)
3. Waits for your first instruction

On first run with an empty project:
1. The system detects that no project exists
2. Offers to scaffold a new Android project (Kotlin, Jetpack Compose, Material 3)
3. After scaffolding, waits for your instructions

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

Simply start the container again and run python main.py. The system detects the checkpoint and asks if you want to continue.


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
   ├── exampleDocker/           # Dockerfile for building the container
   ├── checkpoints/             # SQLite checkpoints (auto-generated)
   ├── logs/                    # Build logs (auto-generated)
   └── documentation/           # Auto-generated dev docs


## ⚙️ Configuration

All configuration is done via environment variables (.env.docker file for Docker usage).

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
