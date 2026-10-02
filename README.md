# sub2api-sharepatch

此仓库为 Sub2API 上游正式版维护两层可独立应用的补丁。PR CI、定时和手动发布都会解析上游最新正式 Release 的 tag 与 commit SHA，并在一次运行中固定使用该 SHA 完成检出、补丁应用、测试和构建。

共享账单保持 `standard` 计费模式。用户（管理员也包括在内）按周期实际扣除的 USD 用量占比分摊 CNY 总额；账单用于线下收款，不触发充值渠道或 CNY 余额扣款。网页更新指向本仓库的正式 Release，Docker 镜像发布到本仓库的 GHCR。

共同账单的当期成员表同时显示「预估总均摊（元）」和「预估已消费（元）」，info 图标提供公式与解释。前者按当前 USD 用量占比分摊整月总额；后者再乘以已过时间占自然月时长的比例，供估计截至目前的费用负担，不代表单笔对话的固定价格。按账单时区推算下月同日同刻，下月无同日则取最后一日，参照 [Google Play 官方规则](https://developer.android.com/google/play/billing/lifecycle/subscriptions#renewals)。时间比例最高 100%，达到预计结束后两列完全一致；总用量为零时两列均显示「—」。点击刷新更新数据时间、用量与折算值。最终结算仍按原规则分摊完整周期总额，零用量时仍均摊；历史账单保持固化。

## 本地应用补丁

本地可用解析器获取最新正式 Release 的 tag 和 commit SHA，再检出该提交：

```sh
UPSTREAM_RELEASE_INFO="$(python3 scripts/resolve-upstream.py)"
UPSTREAM_RELEASE_TAG="$(printf '%s\n' "$UPSTREAM_RELEASE_INFO" | awk -F= '$1 == "upstream_tag" {print $2}')"
UPSTREAM_RELEASE_SHA="$(printf '%s\n' "$UPSTREAM_RELEASE_INFO" | awk -F= '$1 == "upstream_sha" {print $2}')"
printf 'Using upstream release %s (%s)\n' "$UPSTREAM_RELEASE_TAG" "$UPSTREAM_RELEASE_SHA"
git clone https://github.com/Wei-Shaw/sub2api.git ../sub2api-upstream
git -C ../sub2api-upstream checkout --detach "$UPSTREAM_RELEASE_SHA"

python3 scripts/apply-overlay.py \
  --upstream ../sub2api-upstream \
  --upstream-sha "$UPSTREAM_RELEASE_SHA" \
  --patch-repo TeacherLi07/sub2api-sharepatch
python3 scripts/apply-codex-customizations.py \
  --upstream ../sub2api-upstream \
  --upstream-sha "$UPSTREAM_RELEASE_SHA"

cd ../sub2api-upstream/backend/cmd/server
go run -mod=mod github.com/google/wire/cmd/wire
```

两个脚本都会要求明确传入 SHA，并拒绝工作树 SHA 不匹配或缺失唯一锚点的源码。只需要共享账单功能时，只运行 `apply-overlay.py`；Codex 教程定制由第二个脚本独立应用。目标工作树应保持干净；`.work/` 是本地测试数据，不会提交到补丁仓库。

### Codex 使用教程配置

Codex 教程定制与共享账单 overlay 分开放置、分别应用。OpenAI 分组的“使用密钥”教程只显示“Codex CLI (WebSocket)”入口，并默认启用该配置。教程模板位于 [`customizations/codex/frontend/src/sub2apiCodex/codexWebsocketConfig.ts`](customizations/codex/frontend/src/sub2apiCodex/codexWebsocketConfig.ts)，模型默认值和配置文本可直接编辑；模板启用 `api_key_model_discovery = true`，Codex 会从 API 端点获取最新模型列表，前端不再提供本地模型目录下载。CI 与发布流程会依次应用两层补丁。

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

然后执行 `docker compose pull sub2api && docker compose up -d sub2api`。发布工作流在所有测试、镜像运行检查和 Release 附件校验成功后才推进 Linux/amd64 的 `latest` 标签。指定版本时，将镜像标签换成目标 Release 的完整 tag，例如 `v0.2.11-share.3`。

### 网页更新与目录权限

网页更新会在容器内的程序目录 `/app` 创建 `.sub2api-update-*` 临时目录，下载并校验目标平台的 Release 更新包，再通过重命名备份、替换 `/app/sub2api`。服务以 `sub2api` 用户运行，因此 `/app` 目录需要归该用户所有；仅给二进制文件设置属主不足以创建临时目录或重命名文件。源码构建补丁为 `/app` 和 `/app/data` 设置 `sub2api:sub2api` 属主；发布镜像采用上游 `Dockerfile.goreleaser`，沿用其 `/app` 权限配置。

`v0.2.8-share.3` 和 `v0.2.11-share.3` 的已发布镜像缺少 `/app` 目录的属主设置。如果网页更新返回 500 `internal error`，在宿主机的 Compose 部署目录查看后端日志：

```sh
docker compose logs --since 10m --tail 300 sub2api
```

若日志包含 `failed to create temp dir: mkdir /app/.sub2api-update-...: permission denied`，可修复现有容器：

```sh
docker compose exec -u 0 sub2api chown sub2api:sub2api /app
```

修正权限后可直接重试网页更新，更新成功后按页面提示重启服务。这里的 `/app` 是容器内目录；该命令只调整目录自身的属主。

网页更新后的二进制和上述权限修正保存在当前容器的可写层，容器重建后会恢复到 Compose 指定的镜像内容。Docker 部署建议通过拉取、重建目标版本的应用镜像完成持久更新；网页更新后也应同步 Compose 中的镜像标签，以便后续重建使用目标版本。

## 发布产物与重试

发布范围固定为 `linux/amd64`。Release tag 和镜像版本标签保持 `v<上游版本>-share.<补丁修订>`；更新包文件名使用不带 `v` 的版本号，例如 `sub2api_0.2.11-share.4_linux_amd64.tar.gz`。旧版网页更新按平台匹配附件，仍可识别新文件名；历史 Release 附件保持原样。

前端和后端在工作流中各构建一次。`scripts/build-release-assets.py` 校验版本与上游 SHA，生成更新包、元数据和 SHA256 清单，再从已校验的更新包提取二进制生成最小 Docker 构建目录。镜像使用上游 `Dockerfile.goreleaser` 打包这份程序，并包含入口脚本、定价资源与 PostgreSQL 备份工具。发布前通过实际容器检查程序版本、二进制和定价文件哈希、运行用户、更新目录创建与文件重命名权限，以及 `pg_dump`、`psql` 可执行性。

镜像检查通过后先推送独立的 `build-<run_id>-<attempt>` 候选标签，把镜像 digest 写入 `release-metadata.json` 并重算校验清单。随后创建或恢复草稿 Release，上传完整附件并重新校验，生成版本镜像标签，再发布 Release。正式发布最后按元数据中记录的 digest 推进镜像 `latest`，成功后才推进网页更新的 latest Release。预发布使用独立的 `-preview.<run_id>.<attempt>` 版本，不推进 latest。

重试只有在已发布 Release 的附件、校验值、源码提交和镜像 digest 记录完整时才跳过构建；跳过构建后仍会执行正式版本的 latest 推进，恢复上次失败的推进步骤。草稿和不完整的可修改 Release 会重新构建并补齐附件。遇到源码提交冲突、API 权限或网络错误会明确失败；不完整的不可变 Release 需要增加 `PATCH_REVISION` 发布新版本。完整 Release 的附件不会被重写，较旧版本不会覆盖较新的 latest。

GitHub 与 GHCR 的 latest 更新无法跨服务原子提交，因此两步之间仍可能有短暂差异；两个更新渠道均只指向已经完成校验的产物，失败后可重跑工作流恢复。

## 验证

CI 与发布工作流会对上游源码应用补丁，生成 Wire 代码，运行 Go 单元测试、PostgreSQL 集成测试、前端类型检查与 Vitest，构建前端、Linux/amd64 更新包和容器镜像，并检查实际镜像的运行权限与资源。当前发布产物面向 Ubuntu/Linux x64。发布版本格式为 `v<上游版本>-share.<PATCH_REVISION>`；`release-metadata.json` 记录上游 tag、commit、补丁 commit、二进制 SHA256 和发布镜像 digest。

本地 PostgreSQL 生命周期测试通过 `SHAREPATCH_TEST_DATABASE_URL` 启用，例如：

```sh
cd backend
SHAREPATCH_TEST_DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable' \
  go test -tags=integration ./internal/sharepatch -run TestPostgresLifecycleAndGuards -count=1
```
