import { vi } from 'vitest'

// Manual mock for echarts to avoid canvas in jsdom.
// vi.mock('echarts') in test files will use this file instead of auto-mocking.
const chartInstance = {
  setOption: vi.fn(),
  dispose: vi.fn(),
}

export const init = vi.fn(() => chartInstance)
export default { init }
