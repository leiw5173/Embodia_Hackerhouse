#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


POINTS_RE = re.compile(r"^Points:\s*(\d+)\s*$", re.IGNORECASE)
AWARD_RE = re.compile(r"(?mi)^\s*/award\s+(@[A-Za-z0-9-]+)\s*$")


@dataclass(frozen=True)
class Context:
    repo: str
    token: str
    event_path: Path
    db_path: Path


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


def extract_award_targets(comment_body: str) -> List[str]:
    users = []
    for m in AWARD_RE.finditer(comment_body or ""):
        users.append(m.group(1).lstrip("@"))
    # 去重但保序
    seen = set()
    out = []
    for u in users:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def has_award_permission(session: requests.Session, repo: str, actor: str) -> bool:
    # Prefer collaborator permission API; if it fails (public repo, token scopes), fall back to assuming no.
    try:
        data = gh(session, "GET", f"https://api.github.com/repos/{repo}/collaborators/{actor}/permission")
        perm = (data or {}).get("permission") or ""
        return perm in ("admin", "maintain", "write")
    except requests.HTTPError:
        return False


def load_db(path: Path) -> Dict[str, int]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    if isinstance(raw, dict) and "users" in raw and isinstance(raw["users"], dict):
        return {k: int(v.get("points", 0)) for k, v in raw["users"].items() if isinstance(v, dict)}
    if isinstance(raw, dict):
        return {k: int(v) for k, v in raw.items()}
    return {}


def save_db(path: Path, totals: Dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 兼容新结构：写成 {"users": {"u": {"points": N}}, "awards": {...}}
    raw = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            raw = {}
    awards = raw.get("awards") if isinstance(raw, dict) else None
    if not isinstance(awards, dict):
        awards = {}
    out = {
        "users": {u: {"points": int(p)} for u, p in totals.items()},
        "awards": awards,
    }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def get_issue_points(session: requests.Session, repo: str, issue_number: int) -> int:
    issue = gh(session, "GET", f"https://api.github.com/repos/{repo}/issues/{issue_number}")
    pts = parse_points_from_labels(issue.get("labels") or [])
    return int(pts or 0)


def post_comment(session: requests.Session, repo: str, issue_number: int, body: str) -> None:
    gh(
        session,
        "POST",
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
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

    ctx = Context(repo=repo, token=token, event_path=event_path, db_path=db_path)

    event = json.loads(ctx.event_path.read_text(encoding="utf-8"))
    comment_body = ((event.get("comment") or {}).get("body")) or ""
    actor = ((event.get("comment") or {}).get("user") or {}).get("login") or os.getenv("GITHUB_ACTOR", "")
    issue_number = int(((event.get("issue") or {}).get("number")) or 0)

    targets = extract_award_targets(comment_body)
    if not targets:
        print("No /award targets found; skipping")
        return 0

    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {ctx.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "embodia-hackerhouse-award-bot",
        }
    )

    if not actor or not has_award_permission(session, ctx.repo, actor):
        print(f"Actor @{actor} has no permission to award", file=sys.stderr)
        # 不自动删评论，直接回帖提示
        if issue_number:
            post_comment(session, ctx.repo, issue_number, f"⛔️ @{actor} 无权发放积分（需要 write/maintain/admin 权限）。")
        return 0

    points = get_issue_points(session, ctx.repo, issue_number)
    if points <= 0:
        post_comment(
            session,
            ctx.repo,
            issue_number,
            "⛔️ 本 Issue 未设置 `Points: XX` 标签，无法计分。请先添加分值标签再执行 `/award @user`。",
        )
        return 0

    totals = load_db(ctx.db_path)
    for u in targets:
        totals[u] = int(totals.get(u, 0)) + int(points)

    save_db(ctx.db_path, totals)

    # 友好回帖：一次 /award 支持多个用户
    who = ", ".join([f"@{u}" for u in targets])
    post_comment(session, ctx.repo, issue_number, f"✅ 已为 {who} 发放 **{points}** 积分。排行榜将自动刷新。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

