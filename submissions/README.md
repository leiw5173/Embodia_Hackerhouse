# submissions（代码类任务提交区）

所有 **代码类 Quest** 的提交物统一放在 `submissions/` 下，方便维护者 Review、也方便后续整理展示。

## 目录结构（必须遵守）

每个提交用一个独立目录，命名规则：

`submissions/<issueId>-<githubId>-<slug>/`

示例：

- `submissions/12-userA-hello-world/`

目录内至少包含：

- `README.md`（必需）：说明如何运行/复现、产出链接、关联 Issue
- 代码与资源文件（按项目需要）

推荐结构：

```
submissions/
  12-userA-hello-world/
    README.md
    src/
    assets/
```

## README.md 内容规范（必需）

请在你的提交目录内的 `README.md` 写清楚：

- **关联 Issue**：`Fixes #12`（这句必须同时写在 PR 描述里）
- **如何运行**：依赖、安装、启动命令
- **如何验收**：输入/输出、截图或视频链接
- **产出链接**：例如生成的视频 URL、线上体验地址等

## 重要说明

- 同一个 Issue 可以有多人提交：每个人用自己的目录。
- 合并 PR 后会自动按 Issue 的 `Points: XX` 给 **PR 作者**发放积分。

