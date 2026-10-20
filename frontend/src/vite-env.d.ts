/// <reference types="vite/client" />

/**
 * Vite env typings.
 *
 * Declared explicitly rather than falling back to `string`: the rules forbid
 * `any`, and an undeclared `import.meta.env.FOO` silently widens to `any`
 * under Vite's default `ImportMetaEnv`. Anything typed here is guaranteed to
 * exist at build time.
 */
interface ImportMetaEnv {
  /**
   * Absolute backend origin, e.g. `http://localhost:8000`.
   * Leave unset to use same-origin relative paths through the dev proxy.
   */
  readonly VITE_API_BASE_URL?: string;
  /** Proxy target for the Vite dev server. Defaults to `http://localhost:8000`. */
  readonly VITE_BACKEND_URL?: string;
  /** Health-probe target for MLflow. Defaults to `http://localhost:5000`. */
  readonly VITE_MLFLOW_URL?: string;
  /** Health-probe target for Grafana. Defaults to `http://localhost:3001`. */
  readonly VITE_GRAFANA_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
