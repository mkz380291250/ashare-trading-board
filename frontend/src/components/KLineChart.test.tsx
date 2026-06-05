import { render } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

// mock lightweight-charts:jsdom 无 canvas/ResizeObserver,只验证组件渲染+喂数不崩
const setData = vi.fn()
const series = { setData, priceScale: () => ({ applyOptions: vi.fn() }) }
const pane = { setStretchFactor: vi.fn() }
vi.mock('lightweight-charts', () => ({
  createChart: () => ({
    addSeries: () => series,
    panes: () => [pane, pane, pane],
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
  }),
  CandlestickSeries: 'Candle',
  HistogramSeries: 'Hist',
  LineSeries: 'Line',
  CrosshairMode: { Normal: 0 },
}))

import { KLineChart, type Bar } from './KLineChart'

const bars: Bar[] = [
  { t: '2026-06-04T09:31:00', o: 10, h: 11, l: 9, c: 10.5, v: 100 },
  { t: '2026-06-04T09:32:00', o: 10.5, h: 12, l: 10, c: 11.8, v: 200 },
]

describe('KLineChart', () => {
  it('renders without crashing given bars', () => {
    const { container } = render(<KLineChart bars={bars} />)
    expect(container.querySelector('div')).toBeInTheDocument()
    expect(setData).toHaveBeenCalled()
  })

  it('handles empty bars', () => {
    const { container } = render(<KLineChart bars={[]} />)
    expect(container.querySelector('div')).toBeInTheDocument()
  })
})
