import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

describe('vitest setup', () => {
  it('renders a basic element', () => {
    render(<div>hello-backtest</div>)
    expect(screen.getByText('hello-backtest')).toBeInTheDocument()
  })
})
