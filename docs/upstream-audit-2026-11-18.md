# 2026-11-18 上游兼容性审查

上一版补丁以 v0.2.20 完成代码审查，最近成功发布到 v0.2.22-share.9。此次审查从 v0.2.20 核对到 v0.2.23（`5af9afb58`），再核对上游 `main`（`2af3f1e15`）。`main` 在该版本之后只同步了 `backend/cmd/server/VERSION`。补丁修订号更新为 `10`。[发布记录](https://github.com/TeacherLi07/sub2api-sharepatch/releases/tag/v0.2.22-share.9) · [上游比较](https://github.com/Wei-Shaw/sub2api/compare/v0.2.20...v0.2.23) · [主线比较](https://github.com/Wei-Shaw/sub2api/compare/v0.2.23...2af3f1e15)

- **v0.2.21** 修正了 Codex WebSocket 搜索、缓存写入用量及部分模型定价。教程继续使用模板配置默认模型，并从 API 动态发现模型。价格修正通过上游扣费反映到余额差额。[上游比较](https://github.com/Wei-Shaw/sub2api/compare/v0.2.20...v0.2.21)
- **v0.2.22** 新增按用户合并的计费通道。并发请求进入 `ApplyBatch` 时，原补丁的事务标记只在单笔 `Apply` 中设置，批量余额更新会被数据库拒绝，通道随即回退逐笔扣费。现于批量认领去重键之后、有新余额扣费时设置同一事务标记，沿用上游的十进制汇总和锁顺序。[上游合并计费改动](https://github.com/Wei-Shaw/sub2api/pull/8816)
- **v0.2.23** 引入 GPT-6.2 Sol/Astra、Ultra Fast 定价以及缓存 TTL 计量修正。上游仍用统一计费仓库扣余额，共享账单以实际差额分摊。发布失败来自 `groupsOpenAIFast.spec.ts` 对旧提示 `service_tier=ultrafast` 的断言。两种语言的提示已经改为支持范围和套餐说明，补丁仅在新提示与旧断言共存时修正测试，保留发行版文案和其余模型断言。[失败运行](https://github.com/TeacherLi07/sub2api-sharepatch/actions/runs/44256661651) · [上游发布](https://github.com/Wei-Shaw/sub2api/releases/tag/v0.2.23)

管理 MCP、支付和订阅路由、网页更新器及共享账单依赖的用户余额字段在这段范围内使用原有接入点。新迁移用于上游索引、用量汇总和定价，独立于共享账单迁移。Go 版本由工作流按 `backend/go.mod` 自动选用，v0.2.23 使用 Go 1.27.4。

## 应用脚本和测试

- 支付路由插入点改为匹配 `RegisterPaymentRoutes` 调用，允许调整参数、换行或增加依赖。Wire provider 插入点定位到对应声明，也允许上游改写注释。[此前的支付路由失败](https://github.com/TeacherLi07/sub2api-sharepatch/actions/runs/36999567279)
- CC Switch 默认模型按导出常量的名称定位，容许单引号、双引号、类型注解和行尾分号。脚本仍要求匹配唯一声明，配置与教程读取同一模板默认值。[此前的默认模型匹配失败](https://github.com/TeacherLi07/sub2api-sharepatch/actions/runs/42353067138)
- Ultra Fast 兼容调整先确认旧断言已与至少一种语言的提示脱节。测试保留中英文提示存在及包含所支持模型的检查。Python 回归覆盖格式变化、歧义锚点和旧提示仍满足原断言的情况。
- PostgreSQL 回归使用真正的 `ApplyBatch` 和共享账单触发器，检查精确扣费、重试、普通余额写入限制和周期结算。检测到上游提供批量计费接口但找不到对应源码时，应用脚本会明确失败。

## 验证范围

- 两层补丁可应用到 v0.2.15–v0.2.23 和所审查的 `main`。两层在 v0.2.23 也分别独立应用成功。
- v0.2.23 的 Python 回归、Wire 生成、Go 单元测试和共享账单 PostgreSQL 16 集成测试通过。Node 20 下前端类型检查、388 个测试文件中的 3,155 项测试及生产构建通过。
- 本地构建并校验了 `v0.2.23-share.10` Linux/amd64 更新包和镜像构建目录。依赖 Docker 的集成测试及实际镜像运行检查待 GitHub Actions 验证。
