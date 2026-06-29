// frontend/src/components/HealthPanel.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { HealthPanel } from './HealthPanel'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    let body: any = []
    if (url.includes('hit-rate')) body = { window: 30, hit_rate: 0.55, n: 8 }
    else if (url.includes('forward-ic')) body = [{ as_of: '2026-06-28', ic: 0.01, rank_ic: 0.05, n: 4000 }]
    else if (url.includes('policy/actions')) body = [{ id: 1, kind: 'RISK_OFF', as_of: '2026-06-28', trigger: '{}', detail: '停买', status: 'AUTO' }]
    else if (url.includes('equity')) body = [{ as_of: '2026-06-28', cash: 0, market_value: 0, total: 100, drawdown: -0.05 }]
    else if (url.includes('last-run')) body = { as_of: '2026-06-28', started_at: '2026-06-28T22:00:00', finished_at: '2026-06-28T22:06:00', ok: false, failed_steps: ['qlib'] }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) }) as any
  }))
})

describe('HealthPanel', () => {
  it('renders the four health stats', async () => {
    render(<MemoryRouter><HealthPanel accountId={1} /></MemoryRouter>)
    expect(await screen.findByText('近30日胜率')).toBeTruthy()
    expect(await screen.findByText('滚动RankIC')).toBeTruthy()
    expect(await screen.findByText('当前回撤')).toBeTruthy()
    expect(await screen.findByText('今日策略动作')).toBeTruthy()
  })

  it('shows last auto-run time and failed step', async () => {
    render(<MemoryRouter><HealthPanel accountId={1} /></MemoryRouter>)
    expect(await screen.findByText(/上次自动运行/)).toBeTruthy()
    expect(await screen.findByText(/2026-06-28 22:06/)).toBeTruthy()
    expect(await screen.findByText(/失败:qlib/)).toBeTruthy()
  })

  it('shows — not NaN on empty data', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      const body = url.includes('hit-rate') ? { window: 30, hit_rate: null, n: 0 } : []
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) }) as any
    }))
    render(<MemoryRouter><HealthPanel accountId={1} /></MemoryRouter>)
    expect(await screen.findByText('近30日胜率')).toBeTruthy()
    expect(screen.queryByText('NaN')).toBeNull()
    expect(screen.queryByText('NaN%')).toBeNull()
  })
})
