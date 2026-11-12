import type {} from '@testing-library/jest-dom/vitest' // the matcher types only; registration is below
import * as matchers from '@testing-library/jest-dom/matchers'
import { cleanup } from '@testing-library/react'
import { afterEach, expect, vi } from 'vitest'

// V6.6.5: register the jest-dom matchers explicitly. The side-effect entry ('@testing-library/jest-dom/vitest') resolves
// its './dist/matchers' import to a different module instance on some hosts (seen on Windows with Node 22), leaving
// toBeInTheDocument unregistered; extending vitest's own expect works everywhere.
expect.extend(matchers)

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
