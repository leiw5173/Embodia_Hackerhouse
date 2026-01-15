# ChatOps 指令与计分规则

## /award（发放积分）

在某个 Quest Issue 下，由具备仓库 **write/maintain/admin** 权限的维护者评论：

- `/award @UserA`
- `/award @UserA`（换行）`/award @UserB`（一次可发给多人）

系统行为：

- 从该 Issue 的 Labels 里读取分值：`Points: XX`
- 将积分写入 `data/leaderboard.json`
- 自动刷新 `README.md` 中的排行榜区块
- Bot 回帖确认发放成功/失败原因

## 计分数据（JSON 数据库）

积分数据保存在仓库内：

- `data/leaderboard.json`

结构（含去重记录，推荐）：

```json
{
  "users": {
    "userA": { "points": 50 },
    "userB": { "points": 10 }
  },
  "awards": {
    "pr:123:issue:12:user:userA": { "points": 50, "ts": "..." }
  }
}
```

## 常见失败原因

- Issue 没有 `Points: XX` 标签
- 执行 `/award` 的人没有足够权限（需要 write/maintain/admin）

