#!/usr/bin/env python3
"""
Weekly Code Review Agent — Agentic approach
============================================
Runs every Monday via GitHub Actions. Acts as a senior data science and
AI cloud architect mentor, reviewing repository code and project progress
against the plan defined in GitHub issues. Creates a new GitHub issue
titled ``yyyy-mm-dd code review`` with prioritised findings, rationales,
and links to further reading.

Uses **GitHub Models** (https://github.com/marketplace/models) for
inference with **tool/function calling** so the model can actively explore
the repository on demand. This agentic approach removes the single-prompt
payload limit and allows the agent to scan the whole codebase.

Required environment variables
-------------------------------
GITHUB_TOKEN      – GitHub Actions token (issues: write, models: read)
GITHUB_REPOSITORY – owner/repo string, injected automatically by Actions
OPENAI_API_KEY    – Set to the GITHUB_TOKEN value in the workflow

Optional environment variables
-------------------------------
OPENAI_BASE_URL   – Inference endpoint. Defaults to the GitHub Models
                    endpoint (https://models.inference.ai.azure.com).
                    Override for Azure OpenAI or other compatible APIs.
OPENAI_MODEL      – Model name. Defaults to gpt-4.1 (code-optimised, 1M
                    token context window available on GitHub Models).
OPENAI_MAX_TOKENS – Maximum tokens per model response. Defaults to 16384.
OPENAI_TEMPERATURE – Sampling temperature (0.0–2.0). Defaults to 0.4.
MAX_AGENT_TURNS   – Maximum tool-call rounds before aborting. Defaults to 30.
MAX_FILE_BYTES    – Per-file read limit in bytes. Defaults to 200000.
DRY_RUN           – Set to "true" to print the review to stdout instead
                    of creating a GitHub issue (useful for testing).
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from github import Github, GithubException
from github.Issue import Issue
from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]
# GitHub Models uses the GITHUB_TOKEN as the bearer token / API key.
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
# Default to GitHub Models endpoint; can be overridden for other providers.
OPENAI_BASE_URL = (
    os.environ.get("OPENAI_BASE_URL") or "https://models.inference.ai.azure.com"
)
OPENAI_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-4.1"
OPENAI_MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS") or "16384")
OPENAI_TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE") or "0.4")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
# Maximum number of agent turns (tool-call rounds) before aborting.
MAX_AGENT_TURNS = int(os.environ.get("MAX_AGENT_TURNS", "30"))
# Per-file read limit; set to 0 to disable.
MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", "200000"))

REPO_ROOT = Path(".")
EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build",
}
INCLUDE_EXTENSIONS = {
    ".py", ".bicep", ".bicepparam", ".json", ".yml", ".yaml",
    ".md", ".txt", ".toml", ".cfg", ".ini",
}
EXCLUDE_EXTENSIONS = {".pdf"}

# ---------------------------------------------------------------------------
# Tool definitions (passed to the model)
# ---------------------------------------------------------------------------
TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List the files and sub-directories inside a repository directory. "
                "Hidden directories (e.g. .git) and common build artefact directories "
                "are automatically excluded. Use '.' for the repository root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Relative path from the repository root, "
                            "e.g. '.' or 'src/optimizer'."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the full UTF-8 content of a single file. "
                "Returns the file content as a string. "
                "Files larger than MAX_FILE_BYTES will return an error."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file from the repository root.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Case-insensitive substring search across all source files in the "
                "repository. Returns each matching file with the line numbers and "
                "text of every matching line. Useful for finding usages, imports, "
                "configuration keys, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Case-insensitive substring to search for.",
                    },
                    "extensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional list of file extensions to restrict the search, "
                            "e.g. [\".py\", \".yml\"]. Omit to search all source extensions."
                        ),
                    },
                },
                "required": ["pattern"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _resolve_path(path: str) -> Path | None:
    """Resolve *path* safely inside REPO_ROOT.

    Returns ``None`` if the resolved path escapes the repository root or is
    otherwise invalid, so callers can return a safe error response.
    """
    try:
        resolved = (REPO_ROOT / path).resolve()
        resolved.relative_to(REPO_ROOT.resolve())
        return resolved
    except (ValueError, OSError):
        return None


def tool_list_directory(path: str) -> dict:
    """Return files and sub-directories for *path*, excluding build artefacts."""
    resolved = _resolve_path(path)
    if resolved is None or not resolved.exists():
        return {"error": f"Path '{path}' not found or is outside the repository."}
    if not resolved.is_dir():
        return {"error": f"'{path}' is not a directory."}

    files: list[str] = []
    dirs: list[str] = []
    try:
        for item in sorted(resolved.iterdir()):
            if item.name in EXCLUDE_DIRS or item.name.startswith(".git"):
                continue
            rel = str(item.relative_to(REPO_ROOT))
            if item.is_dir():
                dirs.append(rel)
            elif item.is_file() and item.suffix.lower() not in EXCLUDE_EXTENSIONS:
                files.append(rel)
    except PermissionError as exc:
        return {"error": str(exc)}

    return {"path": path, "files": files, "dirs": dirs}


def tool_read_file(path: str) -> dict:
    """Return the UTF-8 content of the file at *path*."""
    resolved = _resolve_path(path)
    if resolved is None:
        return {"error": f"Path '{path}' is outside the repository or invalid."}
    if not resolved.exists():
        return {"error": f"File '{path}' not found."}
    if not resolved.is_file():
        return {"error": f"'{path}' is not a file."}

    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        return {"error": str(exc)}

    if MAX_FILE_BYTES and len(raw) > MAX_FILE_BYTES:
        return {
            "error": (
                f"File '{path}' is {len(raw):,} bytes which exceeds the "
                f"{MAX_FILE_BYTES:,}-byte read limit."
            )
        }

    return {
        "path": path,
        "content": raw.decode("utf-8", errors="replace"),
        "size_bytes": len(raw),
    }


def tool_search_files(pattern: str, extensions: list[str] | None = None) -> dict:
    """Return lines matching *pattern* (case-insensitive) across source files."""
    # Normalise extensions: ensure each has a leading dot (e.g. "py" → ".py").
    if extensions:
        exts = {
            (e.lower() if e.startswith(".") else f".{e.lower()}")
            for e in extensions
        }
    else:
        exts = INCLUDE_EXTENSIONS
    pattern_lower = pattern.lower()
    results: list[dict] = []

    for filepath in sorted(REPO_ROOT.rglob("*")):
        if not filepath.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in filepath.parts):
            continue
        if filepath.suffix.lower() not in exts:
            continue

        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        matches = [
            {"line": lineno, "text": line.rstrip()}
            for lineno, line in enumerate(text.splitlines(), start=1)
            if pattern_lower in line.lower()
        ]
        if matches:
            results.append(
                {"file": str(filepath.relative_to(REPO_ROOT)), "matches": matches}
            )

    return {
        "pattern": pattern,
        "total_files_matched": len(results),
        "results": results,
    }


TOOL_REGISTRY = {
    "list_directory": tool_list_directory,
    "read_file": tool_read_file,
    "search_files": tool_search_files,
}


def dispatch_tool(name: str, arguments: str) -> str:
    """Parse *arguments* JSON, call the named tool, and return a JSON string."""
    try:
        kwargs = json.loads(arguments)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid JSON arguments: {exc}"})

    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool '{name}'."})

    try:
        result = fn(**kwargs)
    except TypeError as exc:
        return json.dumps({"error": f"Tool call error: {exc}"})

    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# System prompt – persona and output format
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a senior data science and AI cloud architect with deep expertise in:

- Azure cloud architecture: Azure Functions (Consumption/Flex), Container Apps \
  Jobs, Service Bus, KEDA event-driven scaling, Bicep IaC, managed identities, \
  RBAC, Application Insights, and Log Analytics.
- Optimisation algorithms: 1D and 2D cutting-stock, bin packing, column \
  generation, linear programming (PuLP/Pyomo/OR-Tools), GPU-accelerated solvers \
  (NVIDIA cuOpt).
- Python best practices: type hints, async patterns, structured logging, \
  error handling, testability, and packaging.
- CI/CD and MLOps on Azure: GitHub Actions, OIDC deployments, reproducible \
  environments, automated testing, and observability.
- Software craftsmanship: SOLID principles, 12-factor app, security-by-design, \
  cost optimisation, and performance engineering.

You are **mentoring** contributors who are completing a 6-week internship to \
build a scalable event-driven 1D cutting-stock optimisation solution on Azure \
using NVIDIA cuOpt. You must be encouraging and educational, treat every finding \
as a learning opportunity, and prioritise actionability over completeness.

You have access to three tools to explore the repository at will:
- **list_directory(path)** — list files and sub-directories at a path.
- **read_file(path)** — read the full content of a specific file.
- **search_files(pattern, extensions?)** — search for a keyword or pattern \
  across all source files.

EXPLORATION STRATEGY
====================
Before writing a single word of the review, explore thoroughly:
1. Call list_directory('.') to map the top-level project structure.
2. Recursively list and read every relevant directory: src/, tests/, infra/, \
   .github/, docs/, and any others you discover.
3. Read ALL source files: Python modules, Bicep templates, workflow YAML, \
   requirements/lock files, README, and configuration files.
4. Use search_files to trace patterns — e.g. error handling, logging calls, \
   environment variable usage, TODO/FIXME comments, hardcoded secrets.
5. Be exhaustive — only stop exploring when you have read every file that \
   could contain meaningful information for the review.

OUTPUT FORMAT
=============
Once exploration is complete, produce a GitHub-flavoured Markdown review \
structured exactly as follows:

## Executive Summary
A concise 2–4 sentence overview of the project's current state and overall \
trajectory.

## Project Plan Progress
Assess progress against each week's goal from the GitHub issues. Use a simple \
table with columns: Week | Goal | Status | Comments.
Status must be one of: ✅ Complete | 🔄 In Progress | ⏳ Not Started | ⚠️ Needs Attention

## Code Review Findings

Group findings under **🔴 High Priority**, **🟡 Medium Priority**, \
**🟢 Low Priority / Nice-to-Have**. For each finding use this template:

### [PRIORITY EMOJI] Finding title

**File(s):** `path/to/file.py`
**Rationale:** Why this matters for scalability, correctness, security, \
or learning.
**Recommended action:** Concrete, specific steps the contributor can take.
**Further reading:** Bulleted list of links (prefer official docs and high-quality \
tutorials).

## Recommended Next Steps
Numbered list of the 3–5 highest-impact actions the contributor should focus \
on this week, in priority order.

## Encouragement
A brief, genuine motivating note for the contributor.
"""


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def get_open_issues(repo) -> list[dict]:
    """Return open issues as plain dicts (excludes PRs and code-review issues).

    Code-review issues generated by this agent are excluded so they don't
    accumulate in the model's context and pollute the Project Plan section.
    """
    result = []
    for issue in repo.get_issues(state="open"):
        if issue.pull_request:
            continue
        label_names = [lbl.name for lbl in issue.labels]
        if "code-review" in label_names:
            continue
        result.append(
            {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body or "",
                "labels": label_names,
                "created_at": issue.created_at.isoformat(),
                "updated_at": issue.updated_at.isoformat(),
            }
        )
    return result


def ensure_label(repo, name: str, color: str = "0075ca", description: str = "") -> None:
    """Create the label if it does not already exist.

    Only a 404 (Not Found) response is treated as "label absent"; any other
    error (permission denied, rate-limit, server error, …) is re-raised so
    the job fails with the real cause rather than silently attempting a
    create that will also fail.
    """
    try:
        repo.get_label(name)
    except GithubException as exc:
        if exc.status != 404:
            raise
        repo.create_label(name=name, color=color, description=description)


def find_existing_issue(repo, title: str) -> Issue | None:
    """Return an open code-review issue with *title*, or ``None``."""
    for issue in repo.get_issues(state="open", labels=["code-review"]):
        if issue.title == title:
            return issue
    return None


def create_github_issue(repo, title: str, body: str) -> str:
    """Create a GitHub issue and return its URL."""
    ensure_label(
        repo,
        "code-review",
        color="1d76db",
        description="Automated weekly code review findings",
    )
    issue = repo.create_issue(title=title, body=body, labels=["code-review"])
    return issue.html_url


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def run_agent(issues: list[dict]) -> str:
    """Run the agentic code-review loop and return the Markdown review text.

    The agent is given tool access to explore the repository freely.  It
    iterates until it stops calling tools and returns a final answer, or
    until MAX_AGENT_TURNS is reached.
    """
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    issues_json = json.dumps(issues, indent=2, ensure_ascii=False)

    initial_user_message = f"""\
Today's date: {today}

## Project Plan — GitHub Issues (open)

```json
{issues_json}
```

Please start by exploring the repository structure using the available tools, \
then thoroughly review the codebase and produce a complete code review and \
project-progress assessment following your instructions exactly.
"""

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": initial_user_message},
    ]

    print(
        f"[agent] Starting agent loop (max {MAX_AGENT_TURNS} turns) …",
        file=sys.stderr,
    )

    for turn in range(1, MAX_AGENT_TURNS + 1):
        print(
            f"[agent] Turn {turn}: calling model '{OPENAI_MODEL}' …",
            file=sys.stderr,
        )

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=OPENAI_TEMPERATURE,
        )

        assistant_message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        # Append assistant turn; serialise tool_calls explicitly for clarity.
        msg_dict: dict[str, object] = {"role": "assistant", "content": assistant_message.content}
        if assistant_message.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_message.tool_calls
            ]
        messages.append(msg_dict)

        if finish_reason == "tool_calls" and assistant_message.tool_calls:
            for tc in assistant_message.tool_calls:
                tool_name = tc.function.name
                tool_args = tc.function.arguments
                preview = tool_args[:120].replace("\n", " ")
                print(
                    f"[agent]   → tool call: {tool_name}({preview})",
                    file=sys.stderr,
                )
                result_str = dispatch_tool(tool_name, tool_args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    }
                )

        elif finish_reason == "stop":
            content = assistant_message.content
            if not content:
                raise RuntimeError(
                    "The model returned an empty response. "
                    "Try increasing OPENAI_MAX_TOKENS or check your API quota."
                )
            print(
                f"[agent] Agent completed after {turn} turn(s).",
                file=sys.stderr,
            )
            return content

        else:
            raise RuntimeError(
                f"Unexpected finish_reason '{finish_reason}' on turn {turn}."
            )

    raise RuntimeError(
        f"Agent did not produce a final review within {MAX_AGENT_TURNS} turns. "
        "Try increasing MAX_AGENT_TURNS."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    gh = Github(GITHUB_TOKEN)
    repo = gh.get_repo(GITHUB_REPOSITORY)

    print("[agent] Fetching open GitHub issues …", file=sys.stderr)
    issues = get_open_issues(repo)
    print(f"[agent] Found {len(issues)} open issues.", file=sys.stderr)

    review_markdown = run_agent(issues)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    issue_title = f"{today} code review"

    # Prepend a header so the issue body is self-contained.
    issue_body = (
        f"# {issue_title}\n\n"
        f"*Generated by the [Weekly Code Review Agent]"
        f"(../../actions/workflows/code-review-agent.yml) "
        f"on {today}.*\n\n---\n\n"
        + review_markdown
    )

    if DRY_RUN:
        print("\n" + "=" * 72, file=sys.stderr)
        print(f"DRY RUN – Issue title: {issue_title}", file=sys.stderr)
        print("=" * 72, file=sys.stderr)
        print(issue_body)
    else:
        existing = find_existing_issue(repo, issue_title)
        if existing:
            print(
                f"[agent] Issue '{issue_title}' already exists: {existing.html_url} — skipping.",
                file=sys.stderr,
            )
        else:
            print(
                f"[agent] Creating GitHub issue '{issue_title}' …",
                file=sys.stderr,
            )
            url = create_github_issue(repo, issue_title, issue_body)
            print(f"[agent] Issue created: {url}", file=sys.stderr)


if __name__ == "__main__":
    main()
