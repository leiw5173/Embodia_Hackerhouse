#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


POINTS_RE = re.compile(r"^Points:\s*(\d+)\s*$", re.IGNORECASE)
LINKED_ISSUE_RE = re.compile(r"(?im)\b(?:fixes|closes|resolves)\s+#(\d+)\b")


@dataclass(frozen=True)
class Db:
    users: Dict[str, int]
    awards: Dict[str, dict]


def gh(session: requests.Session, method: str, url: str, **kwargs):
    r = session.request(method, url, timeout=60, **kwargs)
    r.raise_for_status()
    if r.status_code == 204:
        return None
    return r.json()


def parse_points_from_labels(labels: List[dict]) -> Optional[int]:
    for lb in labels:
        name = (lb.get("name") or "").strip()
        m = POINTS_RE.match(name)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


def extract_linked_issues(pr_body: str) -> List[int]:
    out: List[int] = []
    seen = set()
    for m in LINKED_ISSUE_RE.finditer(pr_body or ""):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def load_db(path: Path) -> Db:
    if not path.exists():
        return Db(users={}, awards={})
    raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    if isinstance(raw, dict) and "users" in raw and isinstance(raw["users"], dict):
        users = {k: int(v.get("points", 0)) for k, v in raw["users"].items() if isinstance(v, dict)}
        awards = raw.get("awards") if isinstance(raw.get("awards"), dict) else {}
        return Db(users=users, awards=awards)
    if isinstance(raw, dict):
        # 兼容旧 KV
        users = {k: int(v) for k, v in raw.items() if isinstance(v, (int, float, str))}
        return Db(users=users, awards={})
    return Db(users={}, awards={})


def save_db(path: Path, db: Db) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "users": {u: {"points": int(p)} for u, p in db.users.items()},
        "awards": db.awards,
    }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def get_issue_points(session: requests.Session, repo: str, issue_number: int) -> int:
    issue = gh(session, "GET", f"https://api.github.com/repos/{repo}/issues/{issue_number}")
    pts = parse_points_from_labels(issue.get("labels") or [])
    return int(pts or 0)


def post_pr_comment(session: requests.Session, repo: str, pr_number: int, body: str) -> None:
    # PR 是 issue 的一种，仍然用 issues comments API
    gh(
        session,
        "POST",
        f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments",
        json={"body": body},
    )


def main() -> int:
    repo = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    event_path = Path(os.getenv("GITHUB_EVENT_PATH", ""))
    db_path = Path(os.getenv("LEADERBOARD_DB", "data/leaderboard.json"))

    if not repo or not token or not event_path.exists():
        print("Missing required GitHub Actions context envs", file=sys.stderr)
        return 2

    event = json.loads(event_path.read_text(encoding="utf-8"))
    pr = event.get("pull_request") or {}
    pr_number = int(pr.get("number") or 0)
    merged = bool(pr.get("merged"))
    pr_author = ((pr.get("user") or {}).get("login")) or ""
    pr_body = (pr.get("body") or "")

    if not merged:
        print("PR not merged; skipping")
        return 0
    if not pr_author:
        print("Missing PR author; skipping", file=sys.stderr)
        return 0

    issue_numbers = extract_linked_issues(pr_body)
    if not issue_numbers:
        # 不报错：只是提醒维护者没写 Fixes #xx
        return 0

    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "embodia-hackerhouse-pr-award-bot",
        }
    )

    db = load_db(db_path)
    total_added = 0
    applied: List[Tuple[int, int]] = []  # (issue, points)
    skipped: List[int] = []

    for issue_number in issue_numbers:
        pts = get_issue_points(session, repo, issue_number)
        if pts <= 0:
            skipped.append(issue_number)
            continue
        award_key = f"pr:{pr_number}:issue:{issue_number}:user:{pr_author}"
        if award_key in db.awards:
            continue
        db.users[pr_author] = int(db.users.get(pr_author, 0)) + int(pts)
        db.awards[award_key] = {
            "repo": repo,
            "pr": pr_number,
            "issue": issue_number,
            "user": pr_author,
            "points": int(pts),
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        total_added += int(pts)
        applied.append((issue_number, int(pts)))

    if total_added <= 0:
        return 0

    save_db(db_path, db)

    # 可选：在 PR 下回帖提示（便于追踪）
    details = ", ".join([f"#{i} (+{p})" for i, p in applied])
    post_pr_comment(session, repo, pr_number, f"✅ 已为 @{pr_author} 发放 **{total_added}** 积分（关联 {details}）。排行榜将自动刷新。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

