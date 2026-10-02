<template>
  <section class="space-y-5 rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white">共同账单</h2>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          按本周期实际扣除的 USD 用量占比分摊管理员设置的 CNY 总额。账单供线下收款。
        </p>
      </div>
      <button class="btn btn-secondary" :disabled="loading" @click="loadDashboard">刷新</button>
    </div>

    <div v-if="error" class="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300">{{ error }}</div>
    <div v-if="notice" class="rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700 dark:bg-green-900/20 dark:text-green-300">{{ notice }}</div>
    <div v-if="loading" class="py-5 text-center text-sm text-gray-500">正在读取账单…</div>

    <template v-else-if="dashboard">
      <div v-if="!dashboard.active" class="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:bg-amber-900/10">
        <p class="font-medium text-amber-900 dark:text-amber-200">共享计费尚未激活</p>
        <p class="mt-1 text-sm text-amber-800 dark:text-amber-300">网关请求目前暂停。管理员完成首次回填和检查后会开放计费。</p>
      </div>

      <template v-else-if="dashboard.current?.cycle">
        <div class="grid gap-3 sm:grid-cols-3">
          <div class="rounded-lg bg-gray-50 p-4 dark:bg-gray-700/50">
            <p class="text-xs text-gray-500 dark:text-gray-400">当前周期</p>
            <p class="mt-1 font-medium text-gray-900 dark:text-white">{{ formatDate(dashboard.current.cycle.starts_at) }} 起</p>
            <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">自然月预计结束：{{ formatDate(dashboard.current.estimated_ends_at) }}</p>
          </div>
          <div class="rounded-lg bg-gray-50 p-4 dark:bg-gray-700/50">
            <p class="text-xs text-gray-500 dark:text-gray-400">全体 USD 用量</p>
            <p class="mt-1 font-mono text-gray-900 dark:text-white">${{ formatTwoDecimals(dashboard.current.total_usd) }}</p>
          </div>
          <div class="rounded-lg bg-gray-50 p-4 dark:bg-gray-700/50">
            <p class="text-xs text-gray-500 dark:text-gray-400">本周期 CNY 总额</p>
            <p class="mt-1 font-mono text-gray-900 dark:text-white">¥{{ dashboard.current.cycle.amount_cny }}</p>
          </div>
        </div>

        <div v-if="isAdmin" class="rounded-lg border border-blue-200 bg-blue-50/50 p-4 dark:border-blue-900 dark:bg-blue-900/10">
          <h3 class="font-medium text-gray-900 dark:text-white">管理员结算</h3>
          <div class="mt-3 flex flex-wrap items-end gap-3">
            <label class="min-w-44 flex-1 text-sm">
              <span class="mb-1 block text-gray-600 dark:text-gray-300">本周期 CNY 总额</span>
              <input v-model="amountCNY" class="input w-full" inputmode="decimal" placeholder="0.00" />
            </label>
            <button class="btn btn-secondary" :disabled="busy || !validCNY(amountCNY)" @click="saveAmount">保存总额</button>
            <button class="btn btn-primary" :disabled="busy" @click="settle">结算并开启下一周期</button>
          </div>
          <p class="mt-2 text-xs text-gray-500 dark:text-gray-400">结算会锁定当前余额边界并固化全员账单，下一周期默认继承本周期总额。</p>
        </div>

        <div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
          <table class="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
            <thead class="bg-gray-50 text-left text-xs uppercase text-gray-500 dark:bg-gray-700/60 dark:text-gray-300">
              <tr>
                <th class="px-4 py-3">成员</th>
                <th class="px-4 py-3 text-right">USD 用量</th>
                <th class="px-4 py-3 text-right">用量占比</th>
                <th class="whitespace-nowrap px-4 py-3 text-right">
                  预估总均摊（元）<HelpTooltip content="个人用量 ÷ 全体用量 × 周期总额。表示按当前用量占比分摊整月总额的预计负担；占比变化时金额也会变化，最终以实际结算为准。分位尾数按结算规则分配。全体用量为零时无法计算，显示 —。" />
                </th>
                <th class="whitespace-nowrap px-4 py-3 text-right">
                  预估已消费（元）<HelpTooltip width-class="w-80" content="个人用量 ÷ 全体用量 ×（周期已过时长 ÷ 自然月周期时长）× 周期总额。假设总额随时间均匀发生，按当前用量占比分摊截至数据时间的折算总额，仅供费用参考；会随全体用量变化，并非单笔对话的固定价格。按账单时区计算至下月同日同刻；无同日取月末，时间比例限制在 0–100%。全体用量为零时无法计算，显示 —。金额四舍五入到分；到达预计结束后与预估总均摊完全一致。" />
                </th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100 dark:divide-gray-700">
              <tr v-for="line in dashboard.current.lines" :key="line.user_id">
                <td class="px-4 py-3 text-gray-900 dark:text-white">{{ line.email }}</td>
                <td class="px-4 py-3 text-right font-mono text-gray-700 dark:text-gray-200">${{ formatTwoDecimals(line.usd_usage) }}</td>
                <td class="px-4 py-3 text-right text-gray-700 dark:text-gray-200">{{ formatTwoDecimals(line.share_percent) }}%</td>
                <td class="px-4 py-3 text-right font-mono text-gray-900 dark:text-white">{{ line.amount_cny === null ? '—' : `¥${line.amount_cny}` }}</td>
                <td class="px-4 py-3 text-right font-mono text-gray-900 dark:text-white">{{ line.prorated_amount_cny === null ? '—' : `¥${line.prorated_amount_cny}` }}</td>
              </tr>
              <tr v-if="dashboard.current.lines.length === 0"><td colspan="5" class="px-4 py-5 text-center text-gray-500">当前没有参与成员</td></tr>
            </tbody>
          </table>
        </div>
        <p class="text-xs text-gray-500 dark:text-gray-400">数据时间：{{ formatDate(dashboard.current.as_of) }}（{{ dashboard.timezone }}）。刷新后更新用量与时间折算；实际结算时间由管理员决定。</p>
      </template>

      <div v-if="dashboard.history.length" class="space-y-3">
        <h3 class="font-medium text-gray-900 dark:text-white">历史结算账单</h3>
        <details v-for="period in dashboard.history" :key="period.cycle.id" class="rounded-lg border border-gray-200 dark:border-gray-700">
          <summary class="cursor-pointer px-4 py-3 text-sm text-gray-800 dark:text-gray-100">
            {{ formatDate(period.cycle.starts_at) }} – {{ period.cycle.ends_at ? formatDate(period.cycle.ends_at) : '' }}
            <span class="ml-2 font-mono">总额 ¥{{ period.cycle.amount_cny }}</span>
          </summary>
          <div class="overflow-x-auto border-t border-gray-200 dark:border-gray-700">
            <table class="min-w-full divide-y divide-gray-100 text-sm dark:divide-gray-700">
              <thead class="bg-gray-50 text-left text-xs text-gray-500 dark:bg-gray-700/60 dark:text-gray-300">
                <tr><th class="px-4 py-2">成员快照</th><th class="px-4 py-2 text-right">USD 用量</th><th class="px-4 py-2 text-right">占比</th><th class="px-4 py-2 text-right">最终 CNY</th></tr>
              </thead>
              <tbody class="divide-y divide-gray-100 dark:divide-gray-700">
                <tr v-for="line in period.lines" :key="line.user_id">
                  <td class="px-4 py-2 text-gray-800 dark:text-gray-100">{{ line.email }}</td>
                  <td class="px-4 py-2 text-right font-mono">${{ formatTwoDecimals(line.usd_usage) }}</td>
                  <td class="px-4 py-2 text-right">{{ formatTwoDecimals(line.share_percent) }}%</td>
                  <td class="px-4 py-2 text-right font-mono">¥{{ line.amount_cny }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>
      </div>

      <div v-if="isAdmin && !dashboard.active" class="rounded-lg border border-gray-200 p-4 dark:border-gray-700">
        <h3 class="font-medium text-gray-900 dark:text-white">首次启用与余额回填</h3>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">起始时间按浏览器本地时区选择，提交时转换为带 UTC 时区的时间。</p>
        <div class="mt-3 grid gap-3 sm:grid-cols-2">
          <label class="text-sm"><span class="mb-1 block text-gray-600 dark:text-gray-300">本周期开始时间</span><input v-model="startsAt" type="datetime-local" class="input w-full" /></label>
          <label class="text-sm"><span class="mb-1 block text-gray-600 dark:text-gray-300">本周期 CNY 总额</span><input v-model="initialAmountCNY" class="input w-full" inputmode="decimal" placeholder="0.00" /></label>
        </div>
        <div class="mt-3 flex flex-wrap gap-2">
          <button class="btn btn-secondary" :disabled="busy || !startsAt || !validCNY(initialAmountCNY)" @click="previewActivation">生成迁移预览</button>
        </div>
        <div v-if="activationPreview" class="mt-4 space-y-3">
          <div class="text-sm text-gray-700 dark:text-gray-200">
            预览区间：{{ formatDate(activationPreview.starts_at) }} – {{ formatDate(activationPreview.cutoff_at) }}；拟纳入 {{ activationPreview.users.length }} 位成员。
          </div>
          <ul v-if="activationPreview.blockers.length" class="space-y-1 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300">
            <li v-for="blocker in activationPreview.blockers" :key="blocker.code">{{ blocker.text }}<span v-if="blocker.count">（{{ blocker.count }}）</span></li>
          </ul>
          <div class="max-h-64 overflow-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table class="min-w-full text-sm">
              <thead class="sticky top-0 bg-gray-50 text-left text-xs text-gray-500 dark:bg-gray-700 dark:text-gray-300"><tr><th class="px-3 py-2">成员</th><th class="px-3 py-2 text-right">日志数</th><th class="px-3 py-2 text-right">回填 USD</th><th class="px-3 py-2 text-right">新余额</th></tr></thead>
              <tbody class="divide-y divide-gray-100 dark:divide-gray-700"><tr v-for="user in activationPreview.users" :key="user.user_id"><td class="px-3 py-2">{{ user.email }}</td><td class="px-3 py-2 text-right">{{ user.usage_log_count }}</td><td class="px-3 py-2 text-right font-mono">${{ formatTwoDecimals(user.usd_usage) }}</td><td class="px-3 py-2 text-right font-mono">${{ user.balance_after_activation }}</td></tr></tbody>
            </table>
          </div>
          <label class="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-200">
            <input v-model="confirmIntegrity" type="checkbox" class="mt-1" />
            <span>我已备份数据库、停止旧实例并等待在途请求和异步日志完成，已暂停日志清理，并从备份或可核验来源确认所选区间的余额计费日志完整。</span>
          </label>
          <button class="btn btn-primary" :disabled="busy || !confirmIntegrity || activationPreview.blockers.length > 0 || activationPreview.active" @click="activate">确认回填并激活</button>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onErrorCaptured, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import HelpTooltip from '@/components/common/HelpTooltip.vue'
import { sharepatchAPI, type SharepatchActivationPreview, type SharepatchDashboard } from './api'
import { sharepatchLog } from './logging'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)
const dashboard = ref<SharepatchDashboard | null>(null)
const activationPreview = ref<SharepatchActivationPreview | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const startsAt = ref('')
const initialAmountCNY = ref('0.00')
const amountCNY = ref('0.00')
const confirmIntegrity = ref(false)
const settlementRetryStorageKey = 'sharepatch.pending-settlement-key'

function loadPendingSettlementKey(): string | null {
  try {
    return sessionStorage.getItem(settlementRetryStorageKey)
  } catch {
    return null
  }
}

function savePendingSettlementKey(key: string | null) {
  try {
    if (key) sessionStorage.setItem(settlementRetryStorageKey, key)
    else sessionStorage.removeItem(settlementRetryStorageKey)
  } catch {
    // Keep the in-memory key for retries when browser storage is unavailable.
  }
}

const pendingSettlementKey = ref<string | null>(loadPendingSettlementKey())

function validCNY(value: string): boolean {
  return /^\d+(?:\.\d{1,2})?$/.test(value.trim())
}

function formatTwoDecimals(value: string | number | null | undefined): string {
  const amount = Number(value)
  return Number.isFinite(amount) ? amount.toFixed(2) : '0.00'
}

function formatDate(value: string): string {
  const timezone = dashboard.value?.timezone || 'Asia/Shanghai'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: timezone }).format(new Date(value))
}

function apiError(err: unknown): string {
  if (err && typeof err === 'object' && 'message' in err && typeof err.message === 'string') return err.message
  return '请求失败，请稍后重试。'
}

function reportFailure(operation: string, err: unknown) {
  sharepatchLog.error(`${operation} failed`, err)
}

async function loadDashboard() {
  loading.value = true
  error.value = ''
  sharepatchLog.debug('dashboard load started')
  try {
    dashboard.value = await sharepatchAPI.getDashboard()
    if (dashboard.value.current?.cycle) amountCNY.value = dashboard.value.current.cycle.amount_cny
    sharepatchLog.info('dashboard loaded', { active: dashboard.value.active, history_count: dashboard.value.history.length })
  } catch (err) {
    reportFailure('dashboard load', err)
    error.value = apiError(err)
  } finally {
    loading.value = false
  }
}

async function previewActivation() {
  busy.value = true
  error.value = ''
  notice.value = ''
  sharepatchLog.info('activation preview started')
  try {
    const localDate = new Date(startsAt.value)
    if (Number.isNaN(localDate.getTime())) throw new Error('请选择有效的周期开始时间。')
    activationPreview.value = await sharepatchAPI.previewActivation(localDate.toISOString(), initialAmountCNY.value.trim())
    confirmIntegrity.value = false
    sharepatchLog.info('activation preview loaded', {
      active: activationPreview.value.active,
      user_count: activationPreview.value.users.length,
      blocker_count: activationPreview.value.blockers.length,
    })
  } catch (err) {
    reportFailure('activation preview', err)
    error.value = apiError(err)
  } finally {
    busy.value = false
  }
}

async function activate() {
  if (!confirmIntegrity.value) return
  busy.value = true
  error.value = ''
  sharepatchLog.info('activation started')
  try {
    const localDate = new Date(startsAt.value)
    await sharepatchAPI.activate(localDate.toISOString(), initialAmountCNY.value.trim())
    notice.value = '共享计费已激活。'
    sharepatchLog.info('activation completed')
    activationPreview.value = null
    await loadDashboard()
  } catch (err) {
    reportFailure('activation', err)
    error.value = apiError(err)
  } finally {
    busy.value = false
  }
}

async function saveAmount() {
  busy.value = true
  error.value = ''
  notice.value = ''
  sharepatchLog.debug('cycle amount update started')
  try {
    await sharepatchAPI.setCurrentAmount(amountCNY.value.trim())
    notice.value = '本周期总额已更新。'
    sharepatchLog.info('cycle amount updated')
    await loadDashboard()
  } catch (err) {
    reportFailure('cycle amount update', err)
    error.value = apiError(err)
  } finally {
    busy.value = false
  }
}

async function settle() {
  busy.value = true
  error.value = ''
  notice.value = ''
  const key = pendingSettlementKey.value ?? (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`)
  pendingSettlementKey.value = key
  savePendingSettlementKey(key)
  sharepatchLog.info('settlement started')
  try {
    const ledger = await sharepatchAPI.settle(key)
    pendingSettlementKey.value = null
    savePendingSettlementKey(null)
    notice.value = `周期 #${ledger.cycle.id} 的账单已固化。`
    sharepatchLog.info('settlement completed', { cycle_id: ledger.cycle.id, line_count: ledger.lines.length })
    await loadDashboard()
  } catch (err) {
    reportFailure('settlement', err)
    error.value = `${apiError(err)} 再次尝试会复用同一结算请求，避免重复结算。`
  } finally {
    busy.value = false
  }
}

watch(() => dashboard.value?.current?.cycle?.amount_cny, (value) => {
  if (value) amountCNY.value = value
})

function onWindowError(event: ErrorEvent) {
  sharepatchLog.error('window error', event.error, { line: event.lineno, column: event.colno })
}

function onUnhandledRejection(event: PromiseRejectionEvent) {
  sharepatchLog.error('unhandled promise rejection', event.reason)
}

onErrorCaptured((err, _instance, source) => {
  sharepatchLog.error('vue component error', err, { source })
})

onMounted(() => {
  window.addEventListener('error', onWindowError)
  window.addEventListener('unhandledrejection', onUnhandledRejection)
  void loadDashboard()
})

onBeforeUnmount(() => {
  window.removeEventListener('error', onWindowError)
  window.removeEventListener('unhandledrejection', onUnhandledRejection)
})
</script>
