import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import HelpTooltip from '@/components/common/HelpTooltip.vue'
import SharepatchPanel from '../SharepatchPanel.vue'
import { sharepatchAPI, type SharepatchDashboard } from '../api'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAdmin: false }) }))
vi.mock('../api', () => ({ sharepatchAPI: { getDashboard: vi.fn() } }))

function dashboard(): SharepatchDashboard {
  return {
    active: true,
    timezone: 'Asia/Shanghai',
    current: {
      cycle: { id: 1, starts_at: '2026-01-31T06:15:00Z', amount_cny: '300.00', status: 'current' },
      as_of: '2026-02-01T06:15:00Z',
      estimated_ends_at: '2026-02-28T06:15:00Z',
      total_usd: '1.00000000',
      lines: [{ user_id: 1, email: 'member@example.test', usd_usage: '1.00000000', share_percent: '100.00000000', amount_cny: '300.00', prorated_amount_cny: '10.71' }],
    },
    history: [],
  }
}

describe('shared billing estimates', () => {
  let wrapper: VueWrapper | undefined

  beforeEach(() => vi.clearAllMocks())
  afterEach(() => {
    wrapper?.unmount()
    document.body.innerHTML = ''
  })

  it('shows both amounts and explains their distinct meaning on hover', async () => {
    vi.mocked(sharepatchAPI.getDashboard).mockResolvedValue(dashboard())
    wrapper = mount(SharepatchPanel, { attachTo: document.body })
    await flushPromises()
    expect(wrapper.text()).toContain('预估总均摊（元）')
    expect(wrapper.text()).toContain('预估已消费（元）')
    const cells = wrapper.findAll('tbody tr')[0]!.findAll('td')
    expect(cells[3]!.text()).toBe('¥300.00')
    expect(cells[4]!.text()).toBe('¥10.71')
    expect(wrapper.text()).toContain('自然月预计结束')
    expect(wrapper.text()).toContain('数据时间')
    const hints = wrapper.findAllComponents(HelpTooltip)
    for (const hint of hints) {
      await hint.trigger('mouseenter')
      const visible = [...document.body.querySelectorAll<HTMLElement>('[role="tooltip"]')].filter(el => el.style.display !== 'none')
      expect(visible).toHaveLength(1)
      expect(visible[0]!.textContent).toContain('个人用量 ÷ 全体用量')
      await hint.trigger('mouseleave')
    }
    expect(hints[1]!.props('content')).toContain('并非单笔对话的固定价格')
  })

  it('shows placeholders for both zero-usage estimates and retains historical amounts', async () => {
    const data = dashboard()
    data.current!.total_usd = '0.00000000'
    const line = data.current!.lines[0]!
    line.usd_usage = '0.00000000'
    line.share_percent = '0.00000000'
    line.amount_cny = null
    line.prorated_amount_cny = null
    data.history = [{ cycle: { ...data.current!.cycle!, id: 0, ends_at: data.current!.cycle!.starts_at, status: 'settled' }, lines: [{ ...line, amount_cny: '300.00' }] }]
    vi.mocked(sharepatchAPI.getDashboard).mockResolvedValue(data)
    wrapper = mount(SharepatchPanel)
    await flushPromises()
    const cells = wrapper.findAll('tbody tr')[0]!.findAll('td')
    expect(cells[3]!.text()).toBe('—')
    expect(cells[4]!.text()).toBe('—')
    expect(wrapper.get('details tbody').text()).toContain('¥300.00')
    expect(wrapper.get('details thead tr').findAll('th')).toHaveLength(4)
  })

  it('refreshes estimates from the same snapshot and spans all five columns for no members', async () => {
    const data = dashboard()
    const updated = dashboard()
    updated.current!.as_of = updated.current!.estimated_ends_at
    updated.current!.lines[0]!.prorated_amount_cny = '300.00'
    vi.mocked(sharepatchAPI.getDashboard).mockResolvedValueOnce(data).mockResolvedValueOnce(updated)
    wrapper = mount(SharepatchPanel)
    await flushPromises()
    await wrapper.get('button').trigger('click')
    await flushPromises()
    const cells = wrapper.findAll('tbody tr')[0]!.findAll('td')
    expect(cells[3]!.text()).toBe(cells[4]!.text())
    const empty = dashboard()
    empty.current!.lines = []
    vi.mocked(sharepatchAPI.getDashboard).mockResolvedValueOnce(empty)
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.get('tbody td').attributes('colspan')).toBe('5')
  })
})
