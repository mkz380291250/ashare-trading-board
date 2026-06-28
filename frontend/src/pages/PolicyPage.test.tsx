import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { PolicyPage } from './PolicyPage'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve([
      { id: 2, kind: 'REMINE', as_of: '2026-06-28', trigger: '{}', detail: '重挖', status: 'AUTO' },
      { id: 1, kind: 'RISK_OFF', as_of: '2026-06-27', trigger: '{}', detail: '停买', status: 'AUTO' },
    ]) }) as any))
})

describe('PolicyPage', () => {
  it('renders policy actions table', async () => {
    render(<PolicyPage />)
    expect(await screen.findByText('策略闸')).toBeTruthy()
    expect(await screen.findByText('重挖')).toBeTruthy()
    expect(await screen.findByText('停买')).toBeTruthy()
  })
})
