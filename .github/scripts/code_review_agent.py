#!/usr/bin/env python3
"""
Weekly Code Review Agent
========================
Runs every Monday via GitHub Actions. Acts as a senior data science and
AI cloud architect mentor, reviewing repository code and project progress
against the plan defined in GitHub issues. Creates a new GitHub issue
titled ``yyyy-mm-dd code review`` with prioritised findings, rationales,
and links to further reading.

Uses **GitHub Models** (https://github.com/marketplace/models) for
inference — no external API key is required. The workflow passes the
automatically-available ``GITHUB_TOKEN`` as the API key and the GitHub
Models endpoint as the base URL.

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
OPENAI_MAX_TOKENS – Maximum tokens in the model response. Defaults to 16384.
OPENAI_TEMPERATURE – Sampling temperature (0.0–2.0). Defaults to 0.4.
DRY_RUN           – Set to "true" to print the review to stdout instead
                    of creating a GitHub issue (useful for testing).
"""

import os
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from github import Github, GithubException
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

# Directories and file extensions to include in the review
INCLUDE_EXTENSIONS = {
    ".py", ".bicep", ".bicepparam", ".json", ".yml", ".yaml",
    ".md", ".txt", ".toml", ".cfg", ".ini",
}
EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build",
}
# Binary or non-reviewable file types to explicitly skip
EXCLUDE_EXTENSIONS = {".pdf"}

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

OUTPUT FORMAT
=============
Respond in GitHub-flavoured Markdown. Structure your response exactly as follows:

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
# Helpers
# ---------------------------------------------------------------------------

def read_repo_files() -> dict[str, str]:
    """Walk the repository and return a mapping of path → content."""
    files: dict[str, str] = {}
    total_chars = 0
    repo_root = Path(".")

    for filepath in sorted(repo_root.rglob("*")):
        if not filepath.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in filepath.parts):
            continue
        if filepath.suffix.lower() in EXCLUDE_EXTENSIONS:
            continue
        if filepath.suffix.lower() not in INCLUDE_EXTENSIONS:
            continue

        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        files[str(filepath)] = content
        total_chars += len(content)

    print(f"[agent] Total characters collected: {total_chars:,}", file=sys.stderr)
    return files


def build_files_section(files: dict[str, str]) -> str:
    """Render repository files as a Markdown code-fenced section."""
    parts: list[str] = []
    for path, content in files.items():
        lang = Path(path).suffix.lstrip(".") or "text"
        parts.append(f"### `{path}`\n\n```{lang}\n{content}\n```\n")
    return "\n".join(parts)


def get_open_issues(repo) -> list[dict]:
    """Return all open issues as plain dicts (excludes pull requests)."""
    result = []
    for issue in repo.get_issues(state="open"):
        if issue.pull_request:
            continue
        result.append(
            {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body or "",
                "labels": [lbl.name for lbl in issue.labels],
                "created_at": issue.created_at.isoformat(),
                "updated_at": issue.updated_at.isoformat(),
            }
        )
    return result


def ensure_label(repo, name: str, color: str = "0075ca", description: str = "") -> None:
    """Create the label if it does not already exist."""
    try:
        repo.get_label(name)
    except GithubException:
        repo.create_label(name=name, color=color, description=description)


def generate_review(files: dict[str, str], issues: list[dict]) -> str:
    """Call the GitHub Models API and return the Markdown review."""
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    issues_json = json.dumps(issues, indent=2, ensure_ascii=False)
    files_section = build_files_section(files)

    user_message = f"""\
Today's date: {today}

---

## Project Plan — GitHub Issues (open)

```json
{issues_json}
```

---

## Repository File Contents

{files_section}

---

Please produce a thorough code review and project-progress assessment following \
your instructions exactly.
"""

    print(f"[agent] Sending request to model '{OPENAI_MODEL}' …", file=sys.stderr)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_tokens=OPENAI_MAX_TOKENS,
        temperature=OPENAI_TEMPERATURE,
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError(
            "The model returned an empty response. "
            "Try increasing OPENAI_MAX_TOKENS or check your API quota."
        )
    return content


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
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("[agent] Reading repository files …", file=sys.stderr)
    files = read_repo_files()
    print(f"[agent] Collected {len(files)} files.", file=sys.stderr)

    gh = Github(GITHUB_TOKEN)
    repo = gh.get_repo(GITHUB_REPOSITORY)

    print("[agent] Fetching open GitHub issues …", file=sys.stderr)
    issues = get_open_issues(repo)
    print(f"[agent] Found {len(issues)} open issues.", file=sys.stderr)

    review_markdown = generate_review(files, issues)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    issue_title = f"{today} code review"

    # Prepend a header so the issue body is self-contained
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
        print(f"[agent] Creating GitHub issue '{issue_title}' …", file=sys.stderr)
        url = create_github_issue(repo, issue_title, issue_body)
        print(f"[agent] Issue created: {url}", file=sys.stderr)


if __name__ == "__main__":
    main()
