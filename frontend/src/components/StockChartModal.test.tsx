import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { type ReactElement } from 'react'
import { StockChartModal } from './StockChartModal'

// useNavigate 需要 Router 上下文
const renderM = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>)

const sampleBars = [
  { t: '2026-06-04T09:31:00', o: 10, h: 11, l: 9, c: 10.5, v: 100 },
]

function stubFetch(bars: any[]) {
  const fn = vi.fn((url: string) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({
      code: '600519.SH', name: '贵州茅台',
      freq: new URL('http://x' + url).searchParams.get('freq'),
      bars, last_time: bars.length ? '2026-06-04T09:31:00' : null,
    }),
  }) as any)
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('StockChartModal', () => {
  beforeEach(() => stubFetch(sampleBars))

  it('fetches and renders period buttons when open', async () => {
    renderM(<StockChartModal code="600519.SH" name="贵州茅台" open onClose={() => {}} />)
    await waitFor(() =>
      expect((globalThis.fetch as any)).toHaveBeenCalledWith(
        expect.stringContaining('/api/kline/600519.SH?freq=day')))  // 默认日线
    expect(screen.getByText('日')).toBeInTheDocument()
    expect(screen.getByText('5分')).toBeInTheDocument()
    expect(screen.getByText('30分')).toBeInTheDocument()
  })

  it('switching period refetches with new freq', async () => {
    renderM(<StockChartModal code="600519.SH" name="贵州茅台" open onClose={() => {}} />)
    await waitFor(() => expect(globalThis.fetch as any).toHaveBeenCalled())
    fireEvent.click(screen.getByText('15分'))
    await waitFor(() =>
      expect((globalThis.fetch as any)).toHaveBeenCalledWith(
        expect.stringContaining('freq=15min')))
  })

  it('shows 采集中 when no bars', async () => {
    stubFetch([])
    renderM(<StockChartModal code="000001.SZ" name="平安" open onClose={() => {}} />)
    await waitFor(() => expect(screen.getByText(/采集中/)).toBeInTheDocument())
  })

  it('does not fetch when closed', () => {
    const fn = stubFetch(sampleBars)
    renderM(<StockChartModal code="600519.SH" open={false} onClose={() => {}} />)
    expect(fn).not.toHaveBeenCalled()
  })
})
