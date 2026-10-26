import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../api'

// A color picker fires a change per pixel of drag, and this applies on the
// spot like the Lighting controls rather than waiting for the pot's save.
const APPLY_DEBOUNCE_MS = 250

const toHex = (rgb) =>
  Array.isArray(rgb) && rgb.length === 3
    ? `#${rgb.map((channel) => Number(channel).toString(16).padStart(2, '0')).join('')}`
    : '#ffffff'

const fromHex = (hex) => {
  const numeric = Number.parseInt(hex.replace('#', ''), 16)
  return { r: (numeric >> 16) & 255, g: (numeric >> 8) & 255, b: numeric & 255 }
}

// The color this pot's stretch of strip shows during its scheduled hours in
// Zone Schedule. Separate from its Manual color on the Controls tab, so
// changing one never changes the other.
export function PotLightColor({ plant, onSaved }) {
  const [color, setColor] = useState(toHex(plant.light_color))
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const timer = useRef(null)

  // Follows the server during render, as the other controls do, except while
  // a change is still waiting to go out: the dashboard refresh would
  // otherwise snap the picker back mid-drag. Compared as hex, since every
  // refresh brings a new array for the same color.
  const served = toHex(plant.light_color)
  const [synced, setSynced] = useState(served)
  if (served !== synced) {
    setSynced(served)
    if (!pending) setColor(served)
  }

  useEffect(() => () => clearTimeout(timer.current), [])

  const change = (value) => {
    setColor(value)
    setPending(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      timer.current = null
      setPending(false)
      try {
        const response = await fetch(`${API_BASE}/plants/${plant.plant_id}/light-color`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(fromHex(value)),
        })
        if (!response.ok) {
          const data = await response.json().catch(() => ({}))
          setError(data.error || `Could not set the color (HTTP ${response.status})`)
          return
        }
        setError('')
        // Brings the plant list up to date. Without it, collapsing the card and
        // opening it again showed the old color: the card starts from the list.
        onSaved?.()
      } catch (failure) {
        setError(`Could not reach the controller: ${failure.message}`)
      }
    }, APPLY_DEBOUNCE_MS)
  }

  return (
    <div className="field-row">
      <label>
        Light color (Zone Schedule)
        <input
          type="color"
          aria-label={`Scheduled light color for ${plant.name}`}
          value={color}
          onChange={(event) => change(event.target.value)}
        />
      </label>
      {error && <p className="field-hint warning">{error}</p>}
    </div>
  )
}
