import { useState } from 'react'
import { API_BASE } from '../api'

const DEFAULT_COLOR_ORDERS = ['RGB', 'RBG', 'GRB', 'GBR', 'BRG', 'BGR']

// Which strip is physically soldered on, and how its channels are wired. Both
// are build-time facts you set once and then forget, which is why they sit on
// the Calibration tab with the other hardware truths rather than next to the
// day-to-day mode and brightness under Controls.
export function LedStripPanel({ overview }) {
  const lighting = overview?.lighting
  const colorOrderOptions = lighting?.color_order_options ?? DEFAULT_COLOR_ORDERS
  const chipOptions = lighting?.chip_options ?? []

  const [chip, setChip] = useState('WS2811')
  const [colorOrder, setColorOrder] = useState('GRB')
  const [status, setStatus] = useState('')
  const [testing, setTesting] = useState('')

  const [syncedOverview, setSyncedOverview] = useState(null)
  if (overview !== syncedOverview) {
    setSyncedOverview(overview)
    setChip(lighting?.chip ?? chip)
    setColorOrder(lighting?.color_order ?? colorOrder)
  }

  // Explicit save, unlike the lighting controls under Controls: selecting a
  // chip resets the colour order to that chip's default, so the two have to be
  // sent in a known order.
  const save = async () => {
    setStatus('')
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
          setStatus(data.error || `Save failed (HTTP ${response.status})`)
          return
        }
      }
      setStatus('Saved.')
    } catch (error) {
      setStatus(`Save failed: ${error.message}`)
    }
  }

  // Lights the whole strip one primary at a time, which is the only way to
  // check the colour order above: if red comes out green, the order is wrong.
  // Deliberately the existing colour endpoint rather than a test mode of its
  // own -- a "test" that drove the strip differently from normal use would
  // prove the test path works, not the strip.
  const show = async (name, rgb) => {
    setTesting('')
    try {
      const response = await fetch(`${API_BASE}/lights/color`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(rgb),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        setTesting(data.error || `Could not set the strip (HTTP ${response.status})`)
        return
      }
      setTesting(
        `Strip set to ${name}. If that is not the colour you see, the colour ` +
          'order above is wrong. This leaves the lights on manually — set the ' +
          'mode back to Schedule under Controls when you are done.',
      )
    } catch (error) {
      setTesting(`Could not set the strip: ${error.message}`)
    }
  }

  return (
    <section className="panel-section">
      <h2>LED strip</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <label>
            LED strip type
            <select value={chip} onChange={(event) => setChip(event.target.value)}>
              {chipOptions.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name} ({option.description})
                </option>
              ))}
            </select>
          </label>
          <p className="field-hint">
            Sets the signal timing for your strip. WS2811 drives three LEDs per
            pixel, so set LED count to a third of the LEDs you can see.
          </p>
        </div>

        <div className="field-row">
          <label>
            LED colour order
            <select value={colorOrder} onChange={(event) => setColorOrder(event.target.value)}>
              {colorOrderOptions.map((order) => (
                <option key={order} value={order}>
                  {order}
                </option>
              ))}
            </select>
          </label>
          <p className="field-hint">
            If red and green look swapped on the strip, try a different order.
            Choosing a strip type resets this to that chip's usual order, so set
            the type first.
          </p>
        </div>

        <button type="button" className="primary group-save-button" onClick={save}>
          Save LED strip
        </button>
        {status && <p className="field-hint warning">{status}</p>}

        <div className="field-row">
          <label>Test the colour order</label>
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
          {testing && <p className="field-hint">{testing}</p>}
        </div>
      </div>
    </section>
  )
}
