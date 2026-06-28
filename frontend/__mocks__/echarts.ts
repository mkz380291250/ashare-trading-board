import { vi } from 'vitest'

// Manual mock for echarts to avoid canvas in jsdom.
// vi.mock('echarts') in test files will use this file instead of auto-mocking.
// Returns a fresh stub object on every call to prevent cross-test bleed.
export const init = vi.fn(() => ({
  setOption: vi.fn(),
  dispose: vi.fn(),
}))

export default { init }
