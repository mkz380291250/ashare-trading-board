import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ScreenerPool } from './ScreenerPool'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve([{ code: "600519.SH", theme: "白酒",
      first_selected_on: "2026-06-01", entry_close: 1800,
      ret_t1: 0.01, ret_t3: 0.02, ret_t5: null, ret_t10: null }]) }) as any))
})

describe('ScreenerPool', () => {
  it('renders a pick row in an antd table', async () => {
    render(<ScreenerPool />)
    await waitFor(() => expect(screen.getByText('600519.SH')).toBeInTheDocument())
    expect(document.querySelector('.ant-table')).toBeTruthy()
  })
})
