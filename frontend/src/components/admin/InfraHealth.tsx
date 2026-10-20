import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, AlertTriangle, XCircle, HelpCircle } from 'lucide-react';
import { Card } from '@/components/ui';
import { useHealth } from '@/api/endpoints/health';
import {
  buildServiceMatrix,
  useDirectServiceProbes,
  type ServiceProbe,
  type ServiceStatus,
} from '@/api/endpoints/infrastructure';
import { apiClient } from '@/api/axios';
import type { DriftStatusResponse } from '@/types/drift';
import type { ModelRegistryResponse } from '@/types/registry';
import './InfraHealth.css';

const STATUS_ICON = {
  up: CheckCircle2,
  degraded: AlertTriangle,
  down: XCircle,
  unknown: HelpCircle,
} as const satisfies Record<ServiceStatus, typeof CheckCircle2>;

const STATUS_TEXT = {
  up: 'Operational',
  degraded: 'Degraded',
  down: 'Down',
  unknown: 'Unknown',
} as const satisfies Record<ServiceStatus, string>;

/**
 * Infrastructure health grid.
 *
 * **Admin-only.** Ports, service names and model telemetry are precisely the
 * detail the product rules keep off Home, Inventory, Orders and Approvals, so
 * this component renders nowhere but `/admin`.
 *
 * Every tile is a measured probe rather than a configured constant, so a service
 * that is actually down shows red instead of continuing to assert health from
 * stale configuration.
 */
export function InfraHealth() {
  const { data: health, isError: healthFailed } = useHealth();
  const drift = useQuery<DriftStatusResponse>({
    queryKey: ['drift-status'],
    queryFn: async () => (await apiClient.get<DriftStatusResponse>('/api/v1/drift-status')).data,
    refetchInterval: 30_000,
    retry: 1,
  });
  const registry = useQuery<ModelRegistryResponse>({
    queryKey: ['model-registry'],
    queryFn: async () => (await apiClient.get<ModelRegistryResponse>('/api/v1/model-registry')).data,
    refetchInterval: 60_000,
    retry: 1,
  });
  const direct = useDirectServiceProbes();

  const probes: ServiceProbe[] = buildServiceMatrix(
    health,
    healthFailed,
    drift.data,
    registry.data,
    direct.data ?? { grafana: null, mlflow: null, prometheus: null },
  );

  return (
    <Card title="Service health">
      {direct.isPending && probes.length === 0 ? (
        <div className="infra-grid" aria-busy="true">
          {[0, 1, 2, 3, 4, 5].map((index) => (
            <div key={index} className="infra-tile">
              <div className="skeleton" style={{ height: 13, width: '55%' }} />
              <div className="skeleton" style={{ height: 22, width: '35%', marginTop: 10 }} />
              <div className="skeleton" style={{ height: 11, width: '80%', marginTop: 10 }} />
            </div>
          ))}
        </div>
      ) : (
        <div className="infra-grid">
          {probes.map((probe) => {
            const Icon = STATUS_ICON[probe.status];
            return (
              <div key={probe.id} className={`infra-tile infra-tile--${probe.status}`}>
                <div className="infra-tile__head">
                  <span className="infra-tile__name">{probe.name}</span>
                  <Icon size={15} className="infra-tile__icon" aria-hidden="true" />
                </div>
                <div className="infra-tile__endpoint mono">{probe.endpoint}</div>
                <div className="infra-tile__status">{STATUS_TEXT[probe.status]}</div>
                <div className="infra-tile__detail">{probe.detail}</div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

export default InfraHealth;
