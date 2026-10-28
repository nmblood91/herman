/**
 * Pick one of a few options, drawn as a single joined pill. For choosing a
 * view of the same thing (moisture or temperature, a time range), which the
 * page's .tab buttons made look like navigation. Buttons with aria-pressed
 * rather than radios: each press takes effect at once, there is no form.
 */
export function Segmented({ label, options, value, onChange, className = '' }) {
  return (
    <div className={`segmented ${className}`.trim()} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
