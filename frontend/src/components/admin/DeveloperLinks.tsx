import { Activity, BookOpen, Database, FlaskConical, type LucideIcon } from 'lucide-react';
import { BACKEND_TOOLS } from '@/types/common';
import './DeveloperLinks.css';

interface Tool {
  name: string;
  description: string;
  /** Published host port. Admin-only surface, per the product rules. */
  port: string;
  url: string;
  icon: LucideIcon;
}

const TOOLS: readonly Tool[] = [
  {
    name: 'Swagger REST docs',
    description: 'Interactive API reference for every endpoint the console calls.',
    port: '8000',
    url: BACKEND_TOOLS.swagger,
    icon: BookOpen,
  },
  {
    name: 'MLflow tracking server',
    description: 'Experiment runs, parameters, metrics and the model registry.',
    port: '5000',
    url: BACKEND_TOOLS.mlflow,
    icon: FlaskConical,
  },
  {
    name: 'Grafana dashboards',
    description: 'Operational metrics and service-level alerting.',
    port: '3001',
    url: BACKEND_TOOLS.grafana,
    icon: Activity,
  },
  {
    name: 'Prometheus server',
    description: 'Raw time-series queries and scrape-target health.',
    port: '9090',
    url: BACKEND_TOOLS.prometheus,
    icon: Database,
  },
];

/**
 * Developer tools launchpad.
 *
 * **Admin-only.** Ports and infrastructure URLs are the detail the product rules
 * keep off every business screen, so this renders nowhere but `/admin` and is
 * deliberately absent from the sidebar.
 *
 * Every link opens in a new tab with `rel="noopener noreferrer"`, which is both
 * a security requirement (`noopener` severs `window.opener`) and what makes
 * "opens in a separate tab" actually true.
 */
export function DeveloperLinks() {
  return (
    <div className="devlinks">
      <div className="devlinks__head">
        <h3 className="devlinks__title">Developer &amp; infrastructure tools</h3>
        <p className="devlinks__subtitle">
          Back-office surfaces for engineers and system operators. These open in a new tab and are
          not part of the pharmacy-facing product.
        </p>
      </div>

      <div className="devlinks__grid">
        {TOOLS.map((tool) => {
          const Icon = tool.icon;
          return (
            <a
              key={tool.url}
              className="devlinks__card"
              href={tool.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className="devlinks__icon" aria-hidden="true">
                <Icon size={18} />
              </span>
              <span className="devlinks__body">
                <span className="devlinks__name">
                  {tool.name}
                  <span className="devlinks__ext" aria-hidden="true">
                    ↗
                  </span>
                </span>
                <span className="devlinks__desc">{tool.description}</span>
                <span className="devlinks__port">:{tool.port}</span>
              </span>
            </a>
          );
        })}
      </div>

      <p className="devlinks__note">
        All targets are local to the demo environment and are not exposed outside it.
      </p>
    </div>
  );
}

export default DeveloperLinks;
