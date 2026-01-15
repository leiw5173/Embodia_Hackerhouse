#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import requests


LEADERBOARD_START = "<!-- LEADERBOARD:START -->"
LEADERBOARD_END = "<!-- LEADERBOARD:END -->"

POINTS_RE = re.compile(r"^Points:\s*(\d+)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class IssueScore:
    number: int
    title: str
    points: int
    assignees: Tuple[str, ...]


def gh_get(session: requests.Session, url: str, params: Optional[dict] = None) -> dict:
    r = session.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def parse_points_from_labels(labels: Iterable[dict]) -> Optional[int]:
    for lb in labels:
        name = (lb.get("name") or "").strip()
        m = POINTS_RE.match(name)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


def extract_issue_scores(issues: List[dict]) -> List[IssueScore]:
    out: List[IssueScore] = []
    for it in issues:
        # GitHub search/issues can return PRs in some endpoints; guard anyway.
        if "pull_request" in it:
            continue
        if (it.get("state") or "").lower() != "closed":
            continue

        points = parse_points_from_labels(it.get("labels") or [])
        if points is None:
            continue

        assignees = tuple(sorted({a.get("login") for a in (it.get("assignees") or []) if a.get("login")}))
        if not assignees:
            # Fallback: if nobody was assigned, attribute to issue author (better than dropping points).
            author = (it.get("user") or {}).get("login")
            assignees = (author,) if author else tuple()

        if not assignees:
            continue

        out.append(
            IssueScore(
                number=int(it.get("number")),
                title=str(it.get("title") or "").strip(),
                points=int(points),
                assignees=assignees,
            )
        )
    return out


def compute_totals(scores: List[IssueScore]) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for s in scores:
        if len(s.assignees) == 0:
            continue
        # 多人协作：默认均分（向下取整），避免一张 Issue 重复计入多个完成者导致总分膨胀
        per = s.points // len(s.assignees)
        if per <= 0:
            continue
        for u in s.assignees:
            totals[u] = totals.get(u, 0) + per
    return totals


def medal_for_points(points: int) -> str:
    if points >= 1500:
        return "🌟 架构师"
    if points >= 1200:
        return "🚀 探索者"
    if points >= 800:
        return "🔥 贡献者"
    if points >= 300:
        return "✨ 新锐"
    return ""


def render_table(totals: Dict[str, int], top_n: int = 20) -> str:
    items = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    items = items[:top_n]

    lines: List[str] = []
    lines.append("## 🏆 开发者荣誉榜（自动更新）")
    lines.append("")
    lines.append("| 排名 | 开发者 | 累计积分 (XP) | 获得勋章 |")
    lines.append("| :--- | :--- | ---: | :--- |")
    for idx, (user, pts) in enumerate(items, start=1):
        rank = "🥇" if idx == 1 else ("🥈" if idx == 2 else ("🥉" if idx == 3 else str(idx)))
        lines.append(f"| {rank} | @{user} | {pts} | {medal_for_points(pts)} |")
    if not items:
        lines.append("| - | - | 0 | |")
    lines.append("")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"> 最近更新：{ts}（由 GitHub Actions 自动生成）")
    return "\n".join(lines)


def replace_between_markers(text: str, replacement: str) -> str:
    if LEADERBOARD_START not in text or LEADERBOARD_END not in text:
        raise RuntimeError("README missing leaderboard markers")
    pre, rest = text.split(LEADERBOARD_START, 1)
    mid, post = rest.split(LEADERBOARD_END, 1)
    _ = mid  # unused
    return f"{pre}{LEADERBOARD_START}\n{replacement}\n{LEADERBOARD_END}{post}"


def fetch_closed_issues_with_labels(session: requests.Session, repo: str) -> List[dict]:
    # Use REST issues list API; labels are included, and it's available by default with GITHUB_TOKEN.
    # We fetch ALL closed issues and filter client-side by Points label for simplicity.
    issues: List[dict] = []
    page = 1
    while True:
        batch = gh_get(
            session,
            f"https://api.github.com/repos/{repo}/issues",
            params={"state": "closed", "per_page": 100, "page": page},
        )
        if not isinstance(batch, list) or not batch:
            break
        issues.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if page > 50:
            # Safety guard: prevents runaway API calls on huge repos for MVP stage
            break
    return issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=False, help="OWNER/REPO（仅当从 GitHub 拉取 issues 时需要）")
    ap.add_argument("--token", required=False, default=os.getenv("GITHUB_TOKEN"), help="GitHub token（或 env GITHUB_TOKEN）")
    ap.add_argument("--from-json", default="data/leaderboard.json", help="从 JSON 数据库读取积分（推荐）")
    ap.add_argument("--from-github", action="store_true", help="从 GitHub issues 计算积分（旧模式，不推荐）")
    ap.add_argument("--readme", default="README.md", help="Path to README to update")
    ap.add_argument("--top", type=int, default=20, help="Top N users")
    args = ap.parse_args()

    totals: Dict[str, int]
    if not args.from_github:
        import json

        with open(args.from_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 支持两种结构：
        # 1) {"userA": 50, "userB": 10}
        # 2) {"users": {"userA": {"points": 50}}}
        if isinstance(data, dict) and "users" in data and isinstance(data["users"], dict):
            totals = {k: int(v.get("points", 0)) for k, v in data["users"].items() if isinstance(v, dict)}
        elif isinstance(data, dict):
            totals = {k: int(v) for k, v in data.items()}
        else:
            totals = {}
    else:
        if not args.repo:
            print("Missing --repo when using --from-github", file=sys.stderr)
            return 2
        if not args.token:
            print("Missing token: pass --token or set GITHUB_TOKEN", file=sys.stderr)
            return 2

        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {args.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "embodia-hackerhouse-leaderboard",
            }
        )

        raw_issues = fetch_closed_issues_with_labels(session, args.repo)
        scores = extract_issue_scores(raw_issues)
        totals = compute_totals(scores)

    rendered = render_table(totals, top_n=args.top)

    with open(args.readme, "r", encoding="utf-8") as f:
        readme = f.read()
    updated = replace_between_markers(readme, rendered)
    if updated != readme:
        with open(args.readme, "w", encoding="utf-8") as f:
            f.write(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

