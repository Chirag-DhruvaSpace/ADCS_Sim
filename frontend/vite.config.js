/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({
  mode
}) => {
  const env = loadEnv(mode, process.cwd(), '');
  const target = env.LEAP_BACKEND_URL || 'http://127.0.0.1:5000';
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  const proxy = Object.fromEntries(['/api', '/assets', '/update', '/rw_telemetry', '/mtr_telemetry', '/ground'].map(prefix => [prefix, {
    target,
    changeOrigin: true
  }]));
  return {
    plugins: [react()],
    base: '/frontend/',
    server: {
      host: '127.0.0.1',
      proxy
    },
    preview: {
      host: '127.0.0.1',
      proxy
    },
    build: {
      target: 'es2022',
      rollupOptions: {
        output: {
          manualChunks: {
            three: ['three'],
            motion: ['gsap']
          }
        }
      }
    }
  };
});
