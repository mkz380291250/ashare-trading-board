import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { Dashboard } from './Dashboard'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const body = url.includes('/api/account/')
      ? { id: 1, name: "测试", cash: 12345.6, positions: [] }
      : []
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) }) as any
  }))
})

describe('Dashboard', () => {
  it('shows cash as a statistic', async () => {
    render(<Dashboard />)
    await waitFor(() => expect(screen.getByText('现金')).toBeInTheDocument())
  })
})
