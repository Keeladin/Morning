import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [VitePWA({
    registerType: 'autoUpdate',
    injectRegister: null,
    includeAssets: ['icons/morning-192.png', 'icons/morning-512.png'],
    manifest: {
      name: 'Morning Shift Reporting', short_name: 'Morning', description: 'Mobile operational shift reporting',
      theme_color: '#315f78', background_color: '#e5e8e9', display: 'standalone', orientation: 'portrait-primary',
      icons: [
        { src: '/icons/morning-192.png', sizes: '192x192', type: 'image/png' },
        { src: '/icons/morning-512.png', sizes: '512x512', type: 'image/png' },
        { src: '/icons/morning-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
      ],
    },
    workbox: {
      globPatterns: ['**/*.{js,css,html,png,svg,woff2}'],
      navigateFallback: '/index.html',
      runtimeCaching: [
        {
          urlPattern: /\/api\/morning\/offline-sync$/,
          method: 'POST',
          handler: 'NetworkOnly',
          options: {
            backgroundSync: {
              name: 'morning-report-sync',
              options: { maxRetentionTime: 24 * 60 },
            },
          },
        },
      ],
    },
  })],
  esbuild: {
    jsx: 'automatic',
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/healthz': 'http://127.0.0.1:8000',
    },
  },
})
