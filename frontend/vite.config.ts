import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'
import { defineConfig, type PluginOption } from 'vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const plugins: PluginOption[] = [react()]
  if (mode === 'analyze') {
    plugins.push(
      visualizer({
        filename: './dist/bundle-stats.html',
        gzipSize: true,
        brotliSize: true,
        open: false,
      }),
    )
  }

  return {
    plugins,
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    build: {
      target: 'es2020',
      sourcemap: false,
      cssCodeSplit: true,
      rollupOptions: {
        output: {
          manualChunks(id: string): string | undefined {
            if (id.includes('node_modules/react') || id.includes('node_modules/react-dom')) {
              return 'react-core'
            }
            if (id.includes('node_modules/@tanstack/react-query')) {
              return 'data-query'
            }
            if (
              id.includes('node_modules/react-hook-form') ||
              id.includes('node_modules/zod') ||
              id.includes('node_modules/@hookform/resolvers')
            ) {
              return 'forms'
            }
            return undefined
          },
        },
      },
    },
    server: {
      port: 5173,
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html'],
        thresholds: {
          lines: 80,
          functions: 80,
          branches: 45,
          statements: 80,
        },
        include: ['src/lib/**/*.ts', 'src/store/**/*.ts', 'src/hooks/**/*.ts'],
      },
    },
  }
})
