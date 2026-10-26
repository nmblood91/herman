import { useState } from 'react'
import { API_BASE } from '../api'

const DEFAULT_COLOR_ORDERS = ['RGB', 'RBG', 'GRB', 'GBR', 'BRG', 'BGR']

// What the picked strip type works out to, before it is saved, so the split
// is visible before anything changes. The chip decides the count because the
// strip is always the same length; LED_COUNT in .env overrides it for a strip
// of another density, and then the count stays put whatever the type.
function PixelCount({ chip, option, zoneCount, fixed }) {
  if (!option?.pixels) return null
  const pixels = option.pixels
  const perZone = zoneCount ? Math.floor(pixels / zoneCount) : null
  return (
    <p className="field-hint">
      {fixed ? `${pixels} pixels, set by LED_COUNT in .env` : `${chip}: ${pixels} pixels`}
      {perZone ? `, ${perZone} per pot.` : '.'}
    </p>
  )
}

// Which strip is physically soldered on, and how its channels are wired. Both
// are build-time facts you set once and then forget, which is why they sit on
// the Calibration tab with the other hardware truths rather than next to the
// day-to-day mode and brightness under Controls.
export function LedStripPanel({ overview }) {
  const lighting = overview?.lighting
  const colorOrderOptions = lighting?.color_order_options ?? DEFAULT_COLOR_ORDERS
  const chipOptions = lighting?.chip_options ?? []
  const zoneCount = lighting?.zones?.length ?? 0

  const [chip, setChip] = useState('WS2811')
  const [colorOrder, setColorOrder] = useState('BRG')
  // {text, warn}: "Saved." is not a warning, a refused save is.
  const [status, setStatus] = useState(null)
  const [testing, setTesting] = useState(null)

  // Choosing a chip resets the color order to that chip's usual one, which is
  // what the planter does when the chip is saved. Shown now, so the order
  // that gets saved is the one on screen; change it after picking the chip.
  const pickChip = (name) => {
    setChip(name)
    const usual = chipOptions.find((option) => option.name === name)?.color_order
    if (usual) setColorOrder(usual)
  }

  // Keyed on the served values, so the periodic refresh does not undo a
  // choice made but not yet saved.
  const served = `${lighting?.chip}|${lighting?.color_order}`
  const [syncedServed, setSyncedServed] = useState(null)
  if (served !== syncedServed) {
    setSyncedServed(served)
    setChip(lighting?.chip ?? chip)
    setColorOrder(lighting?.color_order ?? colorOrder)
  }

  // Explicit save, unlike the lighting controls under Controls: selecting a
  // chip resets the color order to that chip's default, so the two have to be
  // sent in a known order.
  const save = async () => {
    setStatus(null)
    try {
      for (const [path, body] of [
        ['/lights/chip', { chip }],
        ['/lights/color-order', { color_order: colorOrder }],
      ]) {
        const response = await fetch(`${API_BASE}${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!response.ok) {
          const data = await response.json().catch(() => ({}))
          setStatus({ text: data.error || `Save failed (HTTP ${response.status})`, warn: true })
          return
        }
      }
      setStatus({ text: 'Saved.', warn: false })
    } catch (error) {
      setStatus({ text: `Save failed: ${error.message}`, warn: true })
    }
  }

  // Lights the whole strip one primary at a time, which is the only way to
  // check the color order above: if red comes out green, the order is wrong.
  // Deliberately the existing color endpoint rather than a test mode of its
  // own -- a "test" that drove the strip differently from normal use would
  // prove the test path works, not the strip.
  //
  // The whole strip, every time: Manual can be set to color each pot's zone
  // separately, and then a strip-wide color only shows in no zone at all --
  // the test would be read off whatever each zone happened to be set to.
  const show = async (name, rgb) => {
    setTesting(null)
    try {
      for (const [path, body] of [
        ['/lights/manual-scope', { scope: 'all' }],
        ['/lights/color', rgb],
      ]) {
        const response = await fetch(`${API_BASE}${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!response.ok) {
          const data = await response.json().catch(() => ({}))
          setTesting({
            text: data.error || `Could not set the strip (HTTP ${response.status})`,
            warn: true,
          })
          return
        }
      }
      setTesting({
        text:
          `Strip set to ${name}. If that is not the color you see, the color ` +
          'order above is wrong. This leaves the lights on Manual, all zones — ' +
          'set the mode back to Zone Schedule under Controls when you are done.',
        warn: false,
      })
    } catch (error) {
      setTesting({ text: `Could not set the strip: ${error.message}`, warn: true })
    }
  }

  return (
    <section className="panel-section">
      <h2>LED strip</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <label>
            LED strip type
            <select value={chip} onChange={(event) => pickChip(event.target.value)}>
              {chipOptions.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name} ({option.description})
                </option>
              ))}
            </select>
          </label>
          <PixelCount
            chip={chip}
            option={chipOptions.find((option) => option.name === chip)}
            zoneCount={zoneCount}
            fixed={lighting?.led_count_fixed}
          />
        </div>

        <div className="field-row">
          <label>
            LED color order
            <select value={colorOrder} onChange={(event) => setColorOrder(event.target.value)}>
              {colorOrderOptions.map((order) => (
                <option key={order} value={order}>
                  {order}
                </option>
              ))}
            </select>
          </label>
          <p className="field-hint">Picking a strip type resets this to its usual order.</p>
        </div>

        <button type="button" className="primary group-save-button" onClick={save}>
          Save LED strip
        </button>
        {status && <p className={status.warn ? 'field-hint warning' : 'field-hint'}>{status.text}</p>}

        <div className="field-row">
          <label>Test the color order</label>
          <div className="motion-grid">
            <button type="button" onClick={() => show('red', { r: 255, g: 0, b: 0 })}>
              Red
            </button>
            <button type="button" onClick={() => show('green', { r: 0, g: 255, b: 0 })}>
              Green
            </button>
            <button type="button" onClick={() => show('blue', { r: 0, g: 0, b: 255 })}>
              Blue
            </button>
          </div>
          {testing && <p className={testing.warn ? 'field-hint warning' : 'field-hint'}>{testing.text}</p>}
        </div>
      </div>
    </section>
  )
}
