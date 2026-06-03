import '@testing-library/jest-dom'

// antd Row/Col uses window.matchMedia for responsive breakpoints — jsdom doesn't have it
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
})

// ECharts uses canvas.getContext('2d') — provide a minimal stub so it doesn't crash jsdom
// measureText must return { width } so zrender text-measurement doesn't throw
HTMLCanvasElement.prototype.getContext = (() => {
  const ctx: Record<string, unknown> = new Proxy({}, {
    get: (_t, p) => {
      if (p === 'canvas') return document.createElement('canvas')
      if (p === 'measureText') return () => ({ width: 0 })
      return typeof p === 'string' ? () => {} : undefined
    },
    set: () => true,
  })
  return () => ctx
})() as any
