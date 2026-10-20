/**
 * Planning scenarios for the Inventory page.
 *
 * ## These are planning assumptions, not forecasts
 *
 * Each scenario applies a stated adjustment to our demand estimate. Nothing here
 * re-trains a model, and the backend has no endpoint that models a flu season or
 * a supplier delay. The adjustments are the conventional first-pass planning
 * figures, shown next to each toggle so nobody mistakes a stress test for a
 * prediction.
 *
 * `demandMultiplier` scales the expected demand and its range; `safetyFactor`
 * scales only the reorder buffer, which is how a longer lead time actually
 * bites — it does not raise what the pharmacy will consume.
 *
 * Wording is deliberately plain: "Flu Season" and "Supply Delay" are things a
 * pharmacist already plans around, so no statistical vocabulary is needed.
 */

export type ScenarioId = 'normal' | 'flu_season' | 'supply_delay';

export interface Scenario {
  id: ScenarioId;
  /** Button label. */
  label: string;
  /** One line shown under the toggle group. */
  description: string;
  /** Multiplier applied to expected demand and its range. */
  demandMultiplier: number;
  /** Extra buffer on the reorder quantity. 1 = no change. */
  safetyFactor: number;
  /** Short badge text, e.g. "+35% demand". */
  impactLabel: string;
}

export const SCENARIOS: readonly Scenario[] = [
  {
    id: 'normal',
    label: 'Normal',
    description: 'Based on what this pharmacy has been ordering recently.',
    demandMultiplier: 1,
    safetyFactor: 1,
    impactLabel: 'Typical week',
  },
  {
    id: 'flu_season',
    label: 'Flu Season',
    description: 'Expect higher demand for cold, flu and pain products.',
    demandMultiplier: 1.35,
    safetyFactor: 1,
    impactLabel: '+35% demand',
  },
  {
    id: 'supply_delay',
    label: 'Supply Delay',
    description: 'Suppliers are running late, so order extra to cover a longer wait.',
    demandMultiplier: 1,
    safetyFactor: 1.5,
    impactLabel: 'Extra buffer',
  },
] as const;

export const DEFAULT_SCENARIO_ID: ScenarioId = 'normal';

/** Look up a scenario, falling back to `normal` for an unknown id. */
export function findScenario(id: ScenarioId): Scenario {
  return SCENARIOS.find((scenario) => scenario.id === id) ?? (SCENARIOS[0] as Scenario);
}
