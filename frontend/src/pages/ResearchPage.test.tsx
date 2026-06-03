import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ResearchPage } from './ResearchPage'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve([{ code: "600519.SH", as_of: "2026-06-03",
      sentiment: 0.6, rating_consensus: "买入", summary: "机构看多茅台" }]) }) as any))
})

describe('ResearchPage', () => {
  it('lists a researched stock', async () => {
    render(<ResearchPage />)
    await waitFor(() => expect(screen.getByText('600519.SH')).toBeInTheDocument())
  })
})
