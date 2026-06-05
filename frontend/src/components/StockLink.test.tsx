import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { StockChartProvider } from './StockChartProvider'
import { StockLink } from './StockLink'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({
      code: '600519.SH', name: '贵州茅台', freq: '1min', bars: [], last_time: null,
    }),
  }) as any))
})

describe('StockLink', () => {
  it('renders 名称(代码) and opens chart modal on click', async () => {
    render(
      <MemoryRouter><StockChartProvider>
        <StockLink code="600519.SH" name="贵州茅台" />
      </StockChartProvider></MemoryRouter>,
    )
    const link = screen.getByText('贵州茅台(600519.SH)')
    expect(link).toBeInTheDocument()
    fireEvent.click(link)
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
  })

  it('falls back to code when no name', () => {
    render(
      <MemoryRouter><StockChartProvider>
        <StockLink code="600519.SH" />
      </StockChartProvider></MemoryRouter>,
    )
    expect(screen.getByText('600519.SH')).toBeInTheDocument()
  })
})
