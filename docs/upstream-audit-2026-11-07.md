# 上游兼容性审查：v0.2.15–v0.2.20

审查基准为补丁仓库提交 `4a553e93496014027aef9cf81ecdb0996486c6e2`（2026-10-09），目标为上游最新正式 Release `v0.2.20`，固定 SHA `dab829a4e9b7d1cc307189aea8b0319eb29e29d0`。在本仓库 `.work/` 下建立独立检出进行应用与验证，未修改工作区中的其他 Sub2API 实例或数据库备份。

## 已发布版本与来源

逐个下载本仓库 Release 的 `release-metadata.json`，核对上游 tag/commit、补丁 commit 和镜像 digest。下表五个正式版本均来自上述同一个补丁提交；后续每日 workflow 成功还包括已发布完整版本的跳过构建和 latest 恢复检查，不能视为每天都重新构建过。

| 本仓库 Release | 发布时间（UTC） | 元数据中的上游 commit |
| --- | --- | --- |
| [v0.2.15-share.8](https://github.com/TeacherLi07/sub2api-sharepatch/releases/tag/v0.2.15-share.8) | 10-09 12:31 | `f2669c8cf62555cd92389b3f55920e9e6e7c6ff2` |
| [v0.2.16-share.8](https://github.com/TeacherLi07/sub2api-sharepatch/releases/tag/v0.2.16-share.8) | 10-13 11:17 | `01842576b3d5c1e2545b5a99ad555d36e28ed306` |
| [v0.2.17-share.8](https://github.com/TeacherLi07/sub2api-sharepatch/releases/tag/v0.2.17-share.8) | 10-16 09:26 | `060d0160417782cd962a0c7f460f6cd4565d4916` |
| [v0.2.18-share.8](https://github.com/TeacherLi07/sub2api-sharepatch/releases/tag/v0.2.18-share.8) | 10-23 09:46 | `ac1b8f1271be0d674fa6f074403c1410f30a3a81` |
| [v0.2.19-share.8](https://github.com/TeacherLi07/sub2api-sharepatch/releases/tag/v0.2.19-share.8) | 10-28 11:02 | `dece26153621959ccd7635814f4b2d08304e681a` |

## 逐版本追踪

对照上游相邻 tag 的 Git diff，并沿计费、注册、余额写入、路由分发、更新器和 Codex 导出调用路径核查。v0.2.15 到 v0.2.20 共涉及 893 个文件；本审查聚焦补丁插入点及其行为依赖，不等同于对全部上游功能进行完整审计。

| 上游 diff | 与补丁有关的更新 | 结论 |
| --- | --- | --- |
| [0.2.15 → 0.2.16](https://github.com/Wei-Shaw/sub2api/compare/v0.2.15...v0.2.16) | Gemini 显式缓存及存储费、Key/订阅在途预留；Sol 长上下文定价调整；分组多语言 | 存储费仍进入 `RecordUsage` / 统一计费事务，Redis 预留没有改写 `users.balance`。新版价格会影响实际 USD 用量，分摊仍按数据库余额差额计量；无需复制或冻结上游价格规则。 |
| [0.2.16 → 0.2.17](https://github.com/Wei-Shaw/sub2api/compare/v0.2.16...v0.2.17) | 支付/退款回滚、GPT-5.5 订阅退役、Composite 路由修复 | 共享账单已阻断支付入口，余额触发器仍拒绝非计费余额写入；自有 OpenAI 教程使用 `gpt-6-luna`，不依赖退役的 GPT-5.5。保留上游模型映射与路由修复。 |
| [0.2.17 → 0.2.18](https://github.com/Wei-Shaw/sub2api/compare/v0.2.17...v0.2.18) | 断流计费修复、Vertex 配额、按日/周维度优化账号配额 SQL | 主事务依然先认领幂等键、再更新用户余额及账号配额；补丁事务标记位置、事务边界与锁顺序未变。新增有效计费可能改变用户实际消费额，属于上游纠正计量。 |
| [0.2.18 → 0.2.19](https://github.com/Wei-Shaw/sub2api/compare/v0.2.18...v0.2.19) | 细粒度管理员 Key、按实际图片张数计费、Terra 模型 | 管理员 Key 仍经现有 HTTP 路由和全局 Gate，不能绕过共享账单禁止的余额/订阅入口。图片新定价继续走统一计费；新增迁移与 `sharepatch_*` 独立表无命名冲突。 |
| [0.2.19 → 0.2.20](https://github.com/Wei-Shaw/sub2api/compare/v0.2.19...v0.2.20) | 管理 MCP 私有路由；Codex/CC Switch 默认模型、API Key 认证和图片导出；内存预算、流读写上限 | 发现一个发布阻断和一个新的限制绕过入口，均修复；同时保留新增导出行为，详见下文。内存预算和 drain 上限可能改变异常断流时上游可收集的 usage，但共享账单仍以实际已扣余额为准。 |

## 本次修复

1. **发布脚本失效。** [失败运行 42353067138](https://github.com/TeacherLi07/sub2api-sharepatch/actions/runs/42353067138) 的 `Apply sharepatch and Codex customization` 阶段中，overlay 已成功，Codex 脚本因匹配 `OPENAI_CC_SWITCH_CODEX_MODEL = 'gpt-5.5'` 失败而中断。上游 [1e0f56d76](https://github.com/Wei-Shaw/sub2api/commit/1e0f56d76) 已改为 GPT-6.1 Sol。现在按唯一声明定位、读取上游默认模型来调整对应测试，发布不再依赖具体模型名称；补丁自己的默认模型仍由模板决定。
2. **MCP 绕过 HTTP Gate。** v0.2.20 的 `RegisterMCPRoutes` 创建独立 `gin.New()`，工具调用在内部路由分发到余额和订阅管理端点，外层 Gate 只能看到 `/api/v1/mcp`。余额触发器仍会拒绝手工改余额，但它不能阻断订阅授予。现在内部路由也挂载同一个 Gate；新增回归经真实 OAuth/MCP 路由验证余额调整、订阅授予、续期和撤销返回 403，普通 Key 查询继续可用。历史 v0.2.15–v0.2.19 没有该 MCP 入口，不受此问题影响。
3. **保留上游导出改进。** 上游 [0d2459d98](https://github.com/Wei-Shaw/sub2api/commit/0d2459d98) 给 CC Switch 增加了 JSON 载荷，以保留 API Key 认证和图片认证头。旧脚本无条件移除 `configFormat=json`，新脚本只在没有载荷的旧版本移除它。WebSocket 模板保留实时搜索，v0.2.20 API Key 模式保留 `image_generation=true`，沿用上游 API Key 默认认证和重开弹窗时的重置行为；legacy 模式仍可手动选择。
4. **严格拒绝歧义锚点。** 两个脚本原来的 `re.subn(..., count=1)` 无法发现重复正则锚点；现在统计全部匹配，只接受一个，且在失败时不写入文件。CI 和发布解析阶段均运行相应 Python 回归。
5. `PATCH_REVISION` 增至 `9`，避免用新补丁提交覆盖已有 `.share.8` 版本的发布来源。

## 保持的设计与后续方向

没有修改历史迁移、计费算法、结算幂等键、余额触发器或历史账单；无需重置生产余额或重新激活。主计费事务插入点仍然足够小，保留 PostgreSQL NUMERIC、十进制计算和既定锁顺序。继续由上游负责模型价格及 usage 采集，补丁只对最终数据库余额差额分摊，避免复制一套会过期的上游计价逻辑。

后续新增内部路由或旁路服务时，应优先复用共享账单 Gate。Codex 的模型名用结构锚点处理；认证与配置载荷继续复用上游实现，只覆盖自有教程需要的默认值。暂不把整份上游组件替换为自有副本，以免错过新认证、图片及非 OpenAI 平台修复。

## 验证

已完成以下本地检查：

- 最终脚本分别应用到 v0.2.15、v0.2.16、v0.2.17、v0.2.18、v0.2.19、v0.2.20 的干净独立检出，全部成功；v0.2.20 还单独验证 overlay-only 和 Codex-only 应用。
- v0.2.20 Wire 生成、前端类型检查、385 个测试文件 / 3,097 项测试、生产构建通过。
- Python 锚点保护回归、YAML 语法及 `git diff --check` 通过。
- 真实 PostgreSQL 16 下 `go test -tags=integration ./internal/sharepatch -count=1 -v` 通过，包含 `TestPostgresLifecycleAndGuards`。
- 完整单元测试和发布包构建另行记录最终结果。首次本地单元测试的阿里云 SDK 用例受小写 `http_proxy` 环境变量影响；清除大小写代理环境变量后重跑。

本地尝试完整 `go test -tags=integration ./...`：服务层及账单测试通过，依赖 Testcontainers 的仓库/限流测试因运行环境拒绝 Docker 创建网络（`operation not permitted`）失败。实际镜像运行检查同样依赖容器权限；这部分交由 GitHub CI 验证，不将本地部分检查等同于完整 CI 通过。

历史版本这里只重跑补丁应用检查，运行时测试结果来自其发布工作流；本次完整前端及后端检查针对最新 v0.2.20。
