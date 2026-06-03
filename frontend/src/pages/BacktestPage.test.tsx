import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { BacktestPage } from './BacktestPage'

const RUN = {
  id: 1, created_at: "2026-06-03", signal: "momentum",
  start: "2026-01-02", end: "2026-06-01", params: { topk: 8 },
  strategy_metrics: { annualized_return: 0.15, information_ratio: 1.2,
    max_drawdown: -0.08, cum_return: 0.22 },
  factor_report: { ic_mean: 0.07, rank_ic_mean: 0.03,
    layer_returns: [-0.004, -0.002, 0.0, 0.001, 0.003] },
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve(RUN) }) as any))
})

describe('BacktestPage', () => {
  it('shows strategy metrics', async () => {
    render(<BacktestPage />)
    await waitFor(() => expect(screen.getByText('年化收益')).toBeInTheDocument())
  })
})
