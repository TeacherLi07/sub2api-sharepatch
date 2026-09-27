# sub2api-sharepatch

此仓库为 Sub2API 上游正式版维护一个独立叠加补丁。开发与 PR CI 基线固定为上游 `v0.2.8` / `fd80b08c90b55edcad5b00171b53f08721d30da1`；定时与手动发布工作流会读取上游最新正式 Release，并把补丁应用到该 Release 对应的 commit。

共享账单保持 `standard` 计费模式。用户（管理员也包括在内）按周期实际扣除的 USD 用量占比分摊 CNY 总额；账单用于线下收款，不触发充值渠道或 CNY 余额扣款。网页更新指向本仓库的正式 Release，Docker 镜像发布到本仓库的 GHCR。

## 本地应用补丁

将上游仓库检出到计划指定的 commit，再运行：

```sh
python3 scripts/apply-overlay.py \
  --upstream ../sub2api-v0.2.8 \
  --upstream-sha fd80b08c90b55edcad5b00171b53f08721d30da1 \
  --patch-repo TeacherLi07/sub2api-sharepatch

cd ../sub2api-v0.2.8/backend/cmd/server
go run -mod=mod github.com/google/wire/cmd/wire
```

脚本会拒绝 SHA 不符或缺失唯一锚点的源码。目标工作树应保持干净；`.work/` 是本地测试基线，不会提交到补丁仓库。

## 首次启用

补丁迁移创建后，服务处于待激活状态：管理员仍可登录查看迁移预览，网关计费请求会暂停。上线前先停止旧实例，等在途请求与异步使用日志完成，暂停使用日志清理并备份数据库。管理员选择带时区的周期起始时间和 CNY 总额，检查回填日志与阻断项，再确认日志完整性后激活。

启用后余额由数据库触发器保护：只有统一、带请求幂等键的主计费事务可以降低余额；其它余额写入失败。已消费用户不能删除，但可以禁用。每次结算会固定当期余额边界和全员账单，并在同一事务中创建下一周期。账单会保留邮箱快照，后续改名或软删除不会改写历史。

首次迁移仅能基于现存余额计费日志回填。日志完整性、旧实例已停机、清理任务已暂停等条件必须由部署管理员结合真实数据库与备份核实；预览会列出数据库可识别的冻结余额、有效订阅、未结清批量图片任务、清理任务以及已删除用户日志等阻断项。

## 诊断日志

后端插件日志写入标准错误，使用 `SHAREPATCH_LOG_LEVEL=debug|info|warn|error` 设置等级，默认 `info`。前端日志默认 `info`，可在浏览器控制台运行 `localStorage.setItem('sharepatch.log_level', 'debug')` 后刷新页面启用详细记录；也支持 `info`、`warn`、`error` 和 `silent`。日志记录插件操作状态、预览阻断代码与异常类型，不记录账单成员明细或结算幂等键。

## Docker 更新

使用现有 PostgreSQL、Redis、环境变量与数据卷配置，只把应用镜像改为：

```yaml
image: ghcr.io/teacherli07/sub2api-sharepatch:latest
```

然后执行 `docker compose pull sub2api && docker compose up -d sub2api`。发布工作流在所有测试和目标构建成功后才推送多架构 `latest` 标签。

## 验证

发布工作流会对上游源码应用补丁，生成 Wire 代码，运行 Go 单元测试、PostgreSQL 集成测试、前端类型检查与 Vitest，构建前端、Linux/macOS/Windows 二进制及 `linux/amd64`、`linux/arm64` 容器镜像。发布版本格式为 `v<上游版本>-share.<PATCH_REVISION>`；`release-metadata.json` 记录上游 tag、commit 与补丁 commit。

本地 PostgreSQL 生命周期测试通过 `SHAREPATCH_TEST_DATABASE_URL` 启用，例如：

```sh
cd backend
SHAREPATCH_TEST_DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable' \
  go test -tags=integration ./internal/sharepatch -run TestPostgresLifecycleAndGuards -count=1
```
