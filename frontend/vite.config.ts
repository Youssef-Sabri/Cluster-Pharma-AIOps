import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

/**
 * Vite configuration for the ClusterOps dashboard.
 *
 * The dev server proxies the backend's HTTP surface so the browser only ever
 * talks to one origin. That keeps CORS trivial and means the same relative
 * paths work unchanged behind nginx in production, where `nginx.conf` proxies
 * the identical prefixes to `backend:8000`.
 *
 * Five prefixes are proxied, not just `/api`: the backend mounts its REST API
 * under `/api/v1/...` but serves `/health`, `/metrics` and `/docs` at the root,
 * so the TopBar health badge and the monitoring page would 404 otherwise.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const target = env.VITE_BACKEND_URL ?? 'http://localhost:8000';

  const proxy = {
    target,
    changeOrigin: true,
  };

  /** Drop the local prefix so `/mlflow/health` reaches the service at `/health`. */
  const stripPrefix = (path: string): string => path.replace(/^\/(mlflow|grafana)/, '') || '/';

  return {
    plugins: [react()],

    resolve: {
      alias: {
        // `import.meta.url` rather than `__dirname`: package.json sets
        // "type": "module", so the config is evaluated as ESM where `__dirname`
        // does not exist.
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },

    server: {
      port: 3000,
      strictPort: true,
      host: true,
      proxy: {
        '/api': proxy,
        '/health': proxy,
        '/metrics': proxy,
        '/docs': proxy,
        '/openapi.json': proxy,

        /*
         * Cluster services that live on their own compose ports.
         *
         * These exist so the dashboard's infrastructure health matrix can report
         * *measured* reachability rather than a hardcoded "up". The prefix is
         * stripped on the way through, so `/mlflow/health` reaches MLflow at
         * `/health`.
         *
         * A production `nginx.conf` needs the same two locations; only the tiny
         * health endpoints are ever fetched through them, never the UIs.
         */
        '/mlflow': {
          ...proxy,
          target: env.VITE_MLFLOW_URL ?? 'http://localhost:5000',
          rewrite: stripPrefix,
        },
        '/grafana': {
          ...proxy,
          target: env.VITE_GRAFANA_URL ?? 'http://localhost:3001',
          rewrite: stripPrefix,
        },
      },
    },

    preview: {
      port: 3000,
      strictPort: true,
    },

    build: {
      outDir: 'dist',
      /*
       * Source maps are opt-in.
       *
       * `sourcemap: true` added ~3.7 MB of `.map` files to a ~0.6 MB bundle, and
       * the production container serves `dist/` directly — so those maps would be
       * downloadable by anyone, publishing the full component source for no
       * runtime benefit. The dev server does not use them; HMR handles
       * development. Set `VITE_SOURCEMAP=true` when a build needs to be debugged.
       */
      sourcemap: env.VITE_SOURCEMAP === 'true',
      // Split the heavy chart/icon vendors out of the entry chunk so a UI-only
      // change does not invalidate ~300 kB of charting library.
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            charts: ['recharts'],
            query: ['@tanstack/react-query'],
          },
        },
      },
    },
  };
});
