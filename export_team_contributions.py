"""Create auditable team-contribution evidence from repository history."""

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path


COMMIT_MARKER = "@@COMMIT@@"


def read_git_history():
    result = subprocess.run(
        [
            "git", "log", "--no-merges", "--date=short",
            f"--format={COMMIT_MARKER}%H%x1f%an%x1f%ad%x1f%s",
            "--name-only",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def parse_git_history(text):
    commits = []
    current = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(COMMIT_MARKER):
            values = line[len(COMMIT_MARKER):].split("\x1f", 3)
            if len(values) != 4:
                raise ValueError("Unexpected git log record")
            current = {
                "commit": values[0],
                "author": values[1],
                "date": values[2],
                "subject": values[3],
                "files": [],
            }
            commits.append(current)
        elif line and current is not None:
            current["files"].append(line.replace("\\", "/"))
    return commits


def classify_file(path):
    if path.startswith("tests/"):
        return "tests"
    if path.startswith("docs/") or path == "README.md":
        return "documentation"
    if path.startswith("sources/") or path.startswith("data/"):
        return "sources_and_data"
    if path.startswith("static/") or path.startswith("templates/"):
        return "demo_ui"
    if path.startswith("phase2/"):
        return "agent_orchestration"
    if path.startswith("services/") or path in {"data_api.py", "rag.py"}:
        return "qa_and_api"
    if path.startswith("tools/") or path.startswith("conn/"):
        return "ingestion_and_storage"
    return "project_support"


def build_report(commits):
    authors = defaultdict(lambda: {
        "commits": 0, "commit_ids": [], "subjects": [],
        "files": set(), "work_areas": defaultdict(int),
    })
    for commit in commits:
        item = authors[commit["author"]]
        item["commits"] += 1
        item["commit_ids"].append(commit["commit"][:8])
        item["subjects"].append(commit["subject"])
        for path in commit["files"]:
            item["files"].add(path)
            item["work_areas"][classify_file(path)] += 1
    return {
        "evidence_source": "git log --no-merges --name-only",
        "scope_note": (
            "This records committed repository work only. Research, reviews, "
            "presentations, and verbal contributions must be added by the team."
        ),
        "authors": [
            {
                "author": author,
                "commits": value["commits"],
                "commit_ids": value["commit_ids"],
                "subjects": value["subjects"],
                "files_changed": len(value["files"]),
                "work_areas": dict(sorted(value["work_areas"].items())),
            }
            for author, value in sorted(authors.items())
        ],
    }


def markdown_report(report):
    lines = [
        "# Team Contribution Evidence",
        "",
        "This table is generated from committed Git history and is intended "
        "to support, not replace, the team's individual viva explanations.",
        "",
        "| Git author | Commits | Files touched | Observed work areas |",
        "|---|---:|---:|---|",
    ]
    for author in report["authors"]:
        areas = ", ".join(
            f"{name.replace('_', ' ')} ({count})"
            for name, count in author["work_areas"].items()
        ) or "none"
        lines.append(
            f"| {author['author']} | {author['commits']} | "
            f"{author['files_changed']} | {areas} |"
        )
    lines.extend([
        "",
        "## Commit evidence",
        "",
    ])
    for author in report["authors"]:
        lines.append(f"### {author['author']}")
        lines.append("")
        for commit_id, subject in zip(
            author["commit_ids"], author["subjects"]
        ):
            lines.append(f"- `{commit_id}` — {subject}")
        lines.append("")
    lines.extend([
        "## Interpretation boundary",
        "",
        report["scope_note"],
        "",
    ])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json-output",
        default="docs/evidence/team_contributions.json",
    )
    parser.add_argument(
        "--markdown-output",
        default="docs/TEAM_CONTRIBUTIONS.md",
    )
    args = parser.parse_args(argv)
    report = build_report(parse_git_history(read_git_history()))
    json_path = Path(args.json_output)
    markdown_path = Path(args.markdown_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"Team contribution JSON: {json_path.resolve()}")
    print(f"Team contribution Markdown: {markdown_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
