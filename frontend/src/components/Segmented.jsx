/**
 * Pick one of a few options, drawn as a single joined pill. For choosing a
 * view of the same thing (moisture or temperature, a time range), which the
 * page's .tab buttons made look like navigation. Buttons with aria-pressed
 * rather than radios: each press takes effect at once, there is no form.
 * An option with `disabled` is drawn but can't be picked, and its `title`, if
 * any, says why.
 */
export function Segmented({ label, options, value, onChange, className = '' }) {
  return (
    <div className={`segmented ${className}`.trim()} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          disabled={option.disabled}
          title={option.title}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
