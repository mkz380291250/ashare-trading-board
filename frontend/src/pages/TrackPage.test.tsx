import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { TrackPage } from './TrackPage'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve([]) }) as any))
})

describe('TrackPage', () => {
  it('renders paste box and add button', async () => {
    render(<TrackPage />)
    expect(await screen.findByText('添加跟踪')).toBeTruthy()
    expect(screen.getByPlaceholderText(/粘贴/)).toBeTruthy()
  })
})
