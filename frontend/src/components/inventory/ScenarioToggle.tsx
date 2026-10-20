import { SCENARIOS, type ScenarioId } from '@/types/scenario';
import './ScenarioToggle.css';

export interface ScenarioToggleProps {
  activeId: ScenarioId;
  onChange: (id: ScenarioId) => void;
}

/**
 * Three-button planning scenario switch.
 *
 * Buttons, not a slider and not a number field: a pharmacist planning ahead
 * thinks in named situations ("flu season", "suppliers are slow"), not
 * multipliers. The arithmetic behind each is applied silently.
 */
export function ScenarioToggle({ activeId, onChange }: ScenarioToggleProps) {
  const active = SCENARIOS.find((scenario) => scenario.id === activeId) ?? SCENARIOS[0];

  return (
    <div className="stoggle">
      <div className="stoggle__group" role="group" aria-label="Planning scenario">
        {SCENARIOS.map((scenario) => {
          const isActive = scenario.id === activeId;
          return (
            <button
              key={scenario.id}
              type="button"
              className={`stoggle__btn${isActive ? ' stoggle__btn--on' : ''}`}
              onClick={() => onChange(scenario.id)}
              aria-pressed={isActive}
            >
              {scenario.label}
            </button>
          );
        })}
      </div>

      {active ? (
        <p className="stoggle__hint">
          <strong>{active.label}:</strong> {active.description}
        </p>
      ) : null}
    </div>
  );
}

export default ScenarioToggle;
