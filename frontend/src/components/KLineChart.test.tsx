import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { KLineChart, type Bar } from './KLineChart'

const bars: Bar[] = [
  { t: '2026-06-04T09:31:00', o: 10, h: 11, l: 9, c: 10.5, v: 100 },
  { t: '2026-06-04T09:32:00', o: 10.5, h: 12, l: 10, c: 11.8, v: 200 },
]

describe('KLineChart', () => {
  it('renders without crashing given bars', () => {
    const { container } = render(<KLineChart bars={bars} />)
    expect(container.querySelector('div')).toBeInTheDocument()
  })

  it('handles empty bars', () => {
    const { container } = render(<KLineChart bars={[]} />)
    expect(container.querySelector('div')).toBeInTheDocument()
  })
})
