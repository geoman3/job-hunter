# Job Hunter

An AI agent that helps you hunt for jobs: it downloads your resume from Google Drive, searches for matching roles, tailors your resume per job, and researches employers.

Built with:

- **[Google ADK](https://google.github.io/adk-docs/)** — model invocation and workspace `FunctionTool`s (`list_files`, `read_file`, `write_file`, `decode_file`)
- **[Arcade](https://arcade.dev)** via **arcadepy** — Google Drive, Google Search, and Firecrawl

Tools and resources used:

- Cursor
- The Arcade docs https://docs.arcade.dev
- Agent templates https://github.com/ArcadeAI/agent-templates

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended)
- A [Google AI API key](https://aistudio.google.com/apikey) for Gemini
- An [Arcade API key](https://arcade.dev) with Google Drive, Google Search, and Firecrawl enabled for your project

## Setup

```bash
uv sync
cp .env.example .env
# Edit .env with your API keys and ARCADE_USER_ID
```

| Variable | Description |
|----------|-------------|
| `GOOGLE_API_KEY` | Gemini API key for ADK |
| `GOOGLE_GENAI_USE_VERTEXAI` | Set this to `False` |
| `ARCADE_API_KEY` | Arcade API key |
| `ARCADE_USER_ID` | End-user id for Arcade OAuth and tool calls |
| `JOB_HUNTER_WORKSPACE` | Local workspace directory (default: `workspace`) |
| `JOB_HUNTER_MODEL` | Optional Gemini model override |

## Run

```bash
uv run job-hunter
```

Use a specific folder as the workspace (like `cursor .` or `code .`):

```bash
uv run job-hunter .               # current directory
uv run job-hunter ~/my-job-search # explicit path
```

Without a path, the workspace is `JOB_HUNTER_WORKSPACE` from `.env`, or `./workspace` by default.

Example prompts:

- "Find my resume in Google Drive and save it locally, then search for senior Python backend roles remote in the US."
- "Tailor my resume for this job: https://example.com/jobs/123 and research the company."

When the agent calls a tool, you'll see a `[HITL confirm]` prompt — type `yes` to approve or anything else to reject. If Arcade returns an authorization URL, open it in your browser to connect Google Drive, then ask the agent to retry.

## Tests

```bash
uv run pytest
```

## Workspace layout

The agent writes files under `JOB_HUNTER_WORKSPACE` (default: `./workspace`):

```
workspace/
  profile/
    resume.*                 # master resume (from Google Drive)
  jobs/
    <company>-<role>/        # one folder per application
      job-description.md
      research.md
      resume.md
```