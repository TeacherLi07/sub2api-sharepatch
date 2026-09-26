import { apiClient } from '@/api/client'

export interface SharepatchCycle {
  id: number
  starts_at: string
  ends_at?: string
  amount_cny: string
  status: 'current' | 'settled'
}

export interface SharepatchLine {
  user_id: number
  email: string
  status?: string
  created_at?: string
  usd_usage: string
  share_percent: string
  amount_cny: string
}

export interface SharepatchPreview {
  cycle?: SharepatchCycle
  total_usd: string
  lines: SharepatchLine[]
}

export interface SharepatchPeriod {
  cycle: SharepatchCycle
  lines: SharepatchLine[]
}

export interface SharepatchDashboard {
  active: boolean
  timezone: string
  current?: SharepatchPreview
  history: SharepatchPeriod[]
}

export interface SharepatchBlocker {
  code: string
  count?: number
  text: string
}

export interface SharepatchBackfillUser {
  user_id: number
  email: string
  status: string
  created_at: string
  balance_now: string
  balance_after_activation: string
  usage_log_count: number
  usd_usage: string
}

export interface SharepatchActivationPreview {
  active: boolean
  starts_at: string
  cutoff_at: string
  total_cny: string
  users: SharepatchBackfillUser[]
  blockers: SharepatchBlocker[]
  requires_usage_log_integrity_confirmation: boolean
}

export const sharepatchAPI = {
  getDashboard: async () => {
    const response = await apiClient.get<SharepatchDashboard>('/sharepatch/dashboard')
    return response.data
  },
  previewActivation: async (startsAt: string, totalCNY: string) => {
    const response = await apiClient.post<SharepatchActivationPreview>('/admin/sharepatch/activation-preview', {
      starts_at: startsAt,
      total_cny: totalCNY,
    })
    return response.data
  },
  activate: async (startsAt: string, totalCNY: string) => {
    const response = await apiClient.post<SharepatchCycle>('/admin/sharepatch/activate', {
      starts_at: startsAt,
      total_cny: totalCNY,
      confirm_usage_log_integrity: true,
    })
    return response.data
  },
  setCurrentAmount: async (totalCNY: string) => {
    const response = await apiClient.put<SharepatchCycle>('/admin/sharepatch/current-amount', { total_cny: totalCNY })
    return response.data
  },
  settle: async (idempotencyKey: string) => {
    const response = await apiClient.post<SharepatchPeriod>('/admin/sharepatch/settlements', undefined, {
      headers: { 'Idempotency-Key': idempotencyKey },
    })
    return response.data
  },
}
