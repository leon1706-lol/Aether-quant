import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
})

// The 3D scenes mount a WebGL canvas, which jsdom has no implementation
// for. Page-composition tests care about which panels render, not about
// the renderer, so @react-three/fiber and drei are stubbed globally here
// rather than in each test file.
vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: { children?: unknown }) => children,
  useFrame: () => {},
  useThree: () => ({}),
}))

vi.mock('@react-three/drei', () => ({
  Html: ({ children }: { children?: unknown }) => children,
  Line: () => null,
  OrbitControls: () => null,
  Text: ({ children }: { children?: unknown }) => children,
}))
