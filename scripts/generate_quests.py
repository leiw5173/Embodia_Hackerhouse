#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests


QUESTS_START = "<!-- QUESTS:START -->"
QUESTS_END = "<!-- QUESTS:END -->"

POINTS_RE = re.compile(r"^Points:\s*(\d+)\s*$", re.IGNORECASE)
QUEST_TYPE_RE = re.compile(r"^Quest:\s*(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class Quest:
    number: int
    title: str
    quest_type: str
    points: int
    url: str
    state: str


def gh_get(session: requests.Session, url: str, params: Optional[dict] = None) -> dict:
    r = session.get(url, params=params, timeout=60)
    r.raise_for_status()
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


def parse_quest_type_from_labels(labels: List[dict]) -> Optional[str]:
    for lb in labels:
        name = (lb.get("name") or "").strip()
        m = QUEST_TYPE_RE.match(name)
        if m:
            return m.group(1).strip()
    return None


def fetch_open_quests(session: requests.Session, repo: str, debug: bool = False) -> List[Quest]:
    """获取所有开放的 Quest Issue"""
    issues: List[dict] = []
    page = 1
    while True:
        batch = gh_get(
            session,
            f"https://api.github.com/repos/{repo}/issues",
            params={"state": "open", "per_page": 100, "page": page},
        )
        if not isinstance(batch, list) or not batch:
            break
        issues.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if page > 50:
            break

    if debug:
        print(f"Fetched {len(issues)} open issues", file=sys.stderr)

    quests: List[Quest] = []
    skipped_no_quest_type = 0
    skipped_wrong_status = 0
    skipped_pr = 0
    
    for issue in issues:
        # 跳过 PR
        if "pull_request" in issue:
            skipped_pr += 1
            continue
        
        # 检查是否有 Quest 类型标签
        labels = issue.get("labels", [])
        label_names = [lb.get("name", "") for lb in labels]
        issue_title = str(issue.get("title") or "").strip()
        
        if debug:
            issue_num = issue.get("number", 0)
            print(f"Issue #{issue_num}: {issue_title}", file=sys.stderr)
            print(f"  Labels: {', '.join(label_names)}", file=sys.stderr)
        
        quest_type = parse_quest_type_from_labels(labels)
        
        # 如果没有 Quest 类型标签，但标题包含 [Quest] 或使用了 Quest 模板，尝试识别
        if not quest_type:
            # 检查标题是否以 [Quest] 开头（表示使用了 Quest 模板）
            if issue_title.startswith("[Quest]") or issue_title.startswith("[任务]"):
                # 尝试从标题中提取类型，或使用默认类型
                title_lower = issue_title.lower()
                if "learning" in title_lower or "学习" in title_lower:
                    quest_type = "Learning"
                elif "coding" in title_lower or "编程" in title_lower or "代码" in title_lower:
                    quest_type = "Coding"
                elif "promotion" in title_lower or "推广" in title_lower:
                    quest_type = "Promotion"
                else:
                    # 默认使用 Coding 类型
                    quest_type = "Coding"
                
                if debug:
                    print(f"  -> Detected Quest type from title: {quest_type}", file=sys.stderr)
            else:
                skipped_no_quest_type += 1
                if debug:
                    print(f"  -> Skipped: No Quest type label and title doesn't match Quest pattern", file=sys.stderr)
                continue
        
        # 检查状态标签（可选，如果没有 Status: Open 标签也包含）
        has_open_status = any(
            (lb.get("name") or "").strip().lower() == "status: open"
            for lb in labels
        )
        # 如果没有状态标签，默认认为是开放的
        if not has_open_status and any(
            (lb.get("name") or "").strip().lower().startswith("status:")
            for lb in labels
        ):
            # 有其他状态标签但不是 Open，跳过
            skipped_wrong_status += 1
            if debug:
                print(f"  -> Skipped: Wrong status label", file=sys.stderr)
            continue
        
        # 获取分值
        points = parse_points_from_labels(labels)
        if points is None:
            points = 0
        
        if debug:
            print(f"  -> Included: {quest_type}, {points} XP", file=sys.stderr)
        
        quests.append(
            Quest(
                number=int(issue.get("number", 0)),
                title=str(issue.get("title") or "").strip(),
                quest_type=quest_type,
                points=points,
                url=str(issue.get("html_url", "")),
                state=str(issue.get("state", "open")),
            )
        )
    
    if debug:
        print(f"Skipped: {skipped_pr} PRs, {skipped_no_quest_type} issues without Quest type, {skipped_wrong_status} issues with wrong status", file=sys.stderr)
    
    return quests


def quest_type_display_name(quest_type: str) -> str:
    """将 Quest 类型转换为显示名称"""
    type_map = {
        "Learning": "📚 学习",
        "Coding": "💻 编程",
        "Promotion": "📢 推广",
    }
    return type_map.get(quest_type, quest_type)


def render_quests_table(quests: List[Quest]) -> str:
    """渲染任务表格"""
    lines: List[str] = []
    lines.append("## 📋 任务展示界面（自动更新）")
    lines.append("")
    
    if not quests:
        lines.append("> 当前没有开放的任务，请稍后再来查看！")
        lines.append("")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"> 最近更新：{ts}（由 GitHub Actions 自动生成）")
        return "\n".join(lines)
    
    # 按类型分组
    quests_by_type: Dict[str, List[Quest]] = {}
    for quest in quests:
        if quest.quest_type not in quests_by_type:
            quests_by_type[quest.quest_type] = []
        quests_by_type[quest.quest_type].append(quest)
    
    # 按类型顺序显示
    type_order = ["Learning", "Coding", "Promotion"]
    
    for quest_type in type_order:
        if quest_type not in quests_by_type:
            continue
        
        type_quests = quests_by_type[quest_type]
        type_display = quest_type_display_name(quest_type)
        
        lines.append(f"### {type_display}")
        lines.append("")
        lines.append("| 任务 | 分值 | 链接 |")
        lines.append("| :--- | ---: | :--- |")
        
        for quest in sorted(type_quests, key=lambda q: (-q.points, q.number)):
            # 移除标题中的 [Quest] 或 [Quest] 前缀（如果存在）
            title = quest.title
            # 移除常见的任务前缀
            for prefix in ["[Quest]", "[Quest] ", "[任务]", "[任务] "]:
                if title.startswith(prefix):
                    title = title[len(prefix):].strip()
                    break
            
            lines.append(f"| {title} | {quest.points} XP | [#{quest.number}]({quest.url}) |")
        
        lines.append("")
    
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"> 最近更新：{ts}（由 GitHub Actions 自动生成）")
    return "\n".join(lines)


def replace_between_markers(text: str, replacement: str) -> str:
    if QUESTS_START not in text or QUESTS_END not in text:
        raise RuntimeError("README missing quests markers")
    pre, rest = text.split(QUESTS_START, 1)
    mid, post = rest.split(QUESTS_END, 1)
    _ = mid  # unused
    return f"{pre}{QUESTS_START}\n{replacement}\n{QUESTS_END}{post}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="OWNER/REPO（例如：owner/repo）")
    ap.add_argument("--token", required=False, default=os.getenv("GITHUB_TOKEN"), help="GitHub token（或 env GITHUB_TOKEN）")
    ap.add_argument("--readme", default="README.md", help="Path to README to update")
    ap.add_argument("--debug", action="store_true", help="显示调试信息")
    args = ap.parse_args()

    if not args.token:
        print("Missing token: pass --token or set GITHUB_TOKEN", file=sys.stderr)
        return 2

    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {args.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "embodia-hackerhouse-quests",
        }
    )

    quests = fetch_open_quests(session, args.repo, debug=args.debug)
    
    if args.debug:
        print(f"Found {len(quests)} quests", file=sys.stderr)
        for q in quests:
            print(f"  - #{q.number}: {q.title} ({q.quest_type}, {q.points} XP)", file=sys.stderr)
    
    rendered = render_quests_table(quests)

    with open(args.readme, "r", encoding="utf-8") as f:
        readme = f.read()
    
    updated = replace_between_markers(readme, rendered)
    if updated != readme:
        with open(args.readme, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"Updated {len(quests)} quests in README.md")
    else:
        print("No changes to README.md")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
