# 维护者核销与运营流程（Maintainers）

## 日常操作

- 创建 Quest：用 Issue 模板创建，并加好 `Quest:*`、`Points:*`、`Status: Open`
- 审核提交：看评论链接/截图，或 Review/合并 PR
- 发放积分：在对应 Issue 下评论 `/award @User`（可多人）

## 发放前检查清单

- Issue 已加 `Points: XX`
- 完成产出可验证（链接可访问、PR 可运行/可复现等）
- `/award` 执行者具备 write/maintain/admin 权限

## 约定

- 同一 Issue 支持多人成果：用 `/award` 分别发放
- 如需撤销或扣分：建议手动编辑 `data/leaderboard.json`（或后续补 `/penalty` 指令）

