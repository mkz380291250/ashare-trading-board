// frontend/src/components/EquityChart.test.tsx
import { render } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { EquityChart } from './EquityChart'

const setOption = vi.fn()
vi.mock('echarts', () => ({
  init: () => ({ setOption, dispose: vi.fn() }),
}))

describe('EquityChart', () => {
  it('renders without drawdown field (backward compatible)', () => {
    setOption.mockClear()
    render(<EquityChart points={[{ as_of: '2026-06-01', total: 100 }]} />)
    expect(setOption).toHaveBeenCalled()   // 不崩,且不要求 drawdown
  })

  it('adds a drawdown series when drawdown present', () => {
    setOption.mockClear()
    render(<EquityChart points={[{ as_of: '2026-06-01', total: 100, drawdown: -0.05 }]} />)
    const opt = setOption.mock.calls[0][0]
    expect(opt.series.length).toBe(2)      // 净值 + 回撤两条
  })
})
