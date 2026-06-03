import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import App from './App'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve([]) }) as any))
})

describe('App shell', () => {
  it('shows the four menu items', () => {
    render(<MemoryRouter><App /></MemoryRouter>)
    expect(screen.getByText('交易看板')).toBeInTheDocument()
    expect(screen.getByText('选股池')).toBeInTheDocument()
    expect(screen.getByText('研报')).toBeInTheDocument()
    expect(screen.getByText('回测')).toBeInTheDocument()
  })
})
