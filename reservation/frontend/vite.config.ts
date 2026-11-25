import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    // 화면 렌더링 테스트는 두지 않는다. 순수 로직만 node 환경에서 돌린다.
    environment: 'node',
    include: ['src/**/*.test.ts'],
    reporters: ['dot'],
  },
  server: {
    port: 5180,
    proxy: {
      '/api': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
    },
  },
})
