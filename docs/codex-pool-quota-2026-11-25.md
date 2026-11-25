# 2026-11-25 Codex 额度恢复补丁接入

上游 [PR #9024](https://github.com/Wei-Shaw/sub2api/pull/9024) 尚未合并。sharepatch 固定包含其 5 个提交的完整差异，从 `328db26f450edbdf9f8d4344a3ea903ac6396842` 到 `06629eb94471889b2509c6e9b0470ece909a6a75`。源码分支为 `TeacherLi07/sub2api:fix/codex-pool-quota-error`，原工作区未修改。

本次验证基线为最新正式版 v0.2.25，解引用 tag 后的提交为 `348997267d756eab5729bb6b78a275a15d18796a`。应用完整差异无需调整，随后可应用共享账单 overlay、Codex 教程定制并生成 Wire。临时检出均放在 `.work/`。

## CI/CD 行为

- CI 和 CD 先校验补丁 SHA256，再将固定差异应用到干净的正式版检出；保留上游 HEAD，沿用原有精确 SHA 检查。
- 上游已完整包含差异时，通过反向检查跳过；部分采用或冲突时阻断，需要人工审查。不会自动拉取远程分支的新提交。
- 两个工作流均设置 keyword 格式的 `CODEX_POOL_QUOTA_TEST_DSN`，在单元测试阶段执行不依赖 Docker harness 的真实 PostgreSQL 回归。集成阶段继续保留全部原有检查。
- 构建前再次反向检查补丁，避免漏带修复。更新包元数据记录固定来源与哈希；发布与重试校验要求这些信息一致。
- 修订号升至 `12`，v0.2.25 对应 `v0.2.25-share.12`。原 CD 仍为每日 04:23 UTC 和手动触发；手动默认预发布，正式发布才推进镜像及网页更新的 latest。
- 新分组设置默认关闭。发布后的管理员需在 OpenAI 分组中启用，才会返回带 `resets_at` 的账户池额度错误。数据库迁移随二进制分发。

## 本地验证

- Python 10 项回归通过，覆盖 SHA、脏工作树、补丁哈希、冲突无部分应用、上游完整或部分合并。真实 PR HEAD 检出也验证了完整跳过。
- `actionlint` 工作流检查与 Wire 生成通过。
- `go test -tags=unit ./...` 中除 repository 的代理环境问题外均通过；清除代理后 repository 全包重跑通过，且启用了额度 PostgreSQL 测试。Go 使用基线要求的 1.27.4。
- `go test -tags=integration ./...` 完成，共享账单 PostgreSQL 生命周期和保护检查通过；本地无 Docker，repository 的容器集成 harness 跳过。不能将其视为完整 GitHub CI 通过。
- 额度 PostgreSQL 专项测试通过空库、`218_`、`253_` 三个基线，验证迁移、开关持久化、旧写入兼容及额度冷却证据。
- HTTP/WebSocket 额度与相关 WebSocket 限流回归连续运行 10 次通过。
- 前端类型检查、389 个测试文件中的 3,216 项测试、生产构建通过。本地 Node 为 24.20.0，CI 仍使用 Node 20。
- 构建 `v0.2.25-share.12` Linux/amd64 更新包及镜像目录成功；版本、校验清单及固定补丁来源校验通过。未应用额度补丁的检出会在构建前被拒绝，缺失或更改额度来源的元数据也会被拒绝。

实际 Docker 镜像构建、运行权限和容器集成回归仍需 GitHub Actions 验证。远程 CI 与正式 CD 的执行结果以本仓库 Actions 记录为准。
