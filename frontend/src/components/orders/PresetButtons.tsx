import './PresetButtons.css';

export interface PresetButtonsProps {
  onPick: (text: string) => void;
  disabled?: boolean;
  /** Current order text, used to mark an already-loaded preset. */
  current: string;
}

interface Preset {
  label: string;
  text: string;
  hint: string;
}

/**
 * The four demo scenarios.
 *
 * These exist so the matching behaviour can be seen without typing: a clean
 * order, an Arabic one, a badly typed one, and a mixed-script one. The Arabic
 * preset uses Arabic-Indic digits, which the matcher reads as numbers.
 */
const PRESETS: readonly Preset[] = [
  {
    label: 'Clean English',
    text: '10 Panadol Extra 500mg, 5 Augmentin 625mg, 3 Brufen 400mg',
    hint: 'Everything spelled correctly',
  },
  {
    label: 'Arabic',
    text: '١٠ بانادول اكسترا و ٥ كونجستال اقراص و ٣ كتافلام',
    hint: 'Arabic script and Arabic-Indic digits',
  },
  {
    label: 'Messy typing',
    text: '10 panadul xtra, 5 ogmentin 625, 2 catflam 50',
    hint: 'Spelling mistakes and missing forms',
  },
  {
    label: 'Mixed',
    text: '10 panadol extra w 5 congestal 3alashan el-bard',
    hint: 'Latin and Arabic in one line',
  },
];

/** Quick-fill buttons for the order composer. */
export function PresetButtons({ onPick, disabled, current }: PresetButtonsProps) {
  return (
    <div className="presets">
      <span className="presets__label">Try an example</span>
      <div className="presets__row">
        {PRESETS.map((preset) => {
          const isCurrent = current.trim() === preset.text;
          return (
            <button
              key={preset.label}
              type="button"
              className={`presets__btn${isCurrent ? ' presets__btn--on' : ''}`}
              onClick={() => onPick(preset.text)}
              disabled={disabled}
              title={preset.hint}
            >
              {preset.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default PresetButtons;
