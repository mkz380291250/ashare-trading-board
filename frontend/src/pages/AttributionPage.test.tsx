import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AttributionPage } from './AttributionPage'

vi.mock('echarts')   // 避免 canvas

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const body = url.includes('hit-rate')
      ? { window: 30, hit_rate: 0.6, n: 10 }
      : [{ as_of: '2026-06-04', ic: 0.02, rank_ic: 0.07, n: 4000 }]
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) }) as any
  }))
})

describe('AttributionPage', () => {
  it('renders hit-rate stat', async () => {
    render(<AttributionPage />)
    expect(await screen.findByText('归因')).toBeTruthy()
    expect(await screen.findByText(/胜率/)).toBeTruthy()
  })

  it('shows — not NaN on empty data', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      const body = url.includes('hit-rate') ? { window: 30, hit_rate: null, n: 0 } : []
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) }) as any
    }))
    render(<AttributionPage />)
    expect(await screen.findByText('近30日胜率')).toBeTruthy()
    expect(screen.queryByText('NaN')).toBeNull()
    expect(screen.queryByText('NaN%')).toBeNull()
  })
})
