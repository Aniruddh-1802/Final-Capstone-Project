import '@testing-library/jest-dom/vitest'

// Recharts' ResponsiveContainer needs ResizeObserver, which jsdom does not provide.
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }