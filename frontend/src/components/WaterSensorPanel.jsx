import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

// The liquid sensor on the outlet tube, which confirms each dose delivered.
//
// Three readings prove the wiring, and each catches something the others
// cannot. Full and empty prove it sees water the right way round. Unplugged
// proves the fail-safe: with the inverted pin (^!PC1), a loose signal wire is
// pulled high and reads dry, so a dead sensor flags doses rather than
// confirming them. The old non-inverted config passes the first two and fails
// only this one.
const STEPS = [
  {
    key: 'full',
    title: 'Tube full',
    expectWet: true,
    how:
      'Point the nozzle into a jug and run the pump from the Pump panel above, ' +
      'then check while it is running. The falling leg drains as soon as the ' +
      'pump stops, so a stopped pump is not a full tube. On the bench, a ' +
      'water-filled offcut of the same tube works too.',
  },
  {
    key: 'empty',
    title: 'Tube empty',
    expectWet: false,
    how:
      'Pump stopped, and a few seconds for the falling leg to drain into the jug.',
  },
  {
    key: 'unplugged',
    title: 'Signal wire unplugged',
    expectWet: false,
    how:
      'Pull the green wire out of Y-STOP, check, then plug it back in. This is ' +
      'the fail-safe: a loose wire has to read dry so that doses get flagged.',
  },
]

async function readSensor() {
  try {
    const response = await fetch(`${API_BASE}/diagnostics/water-sensor`)
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      return {
        ok: false,
        detail:
          data.error ||
          data.detail ||
          `Request failed (HTTP ${response.status}). If this is a 404, the ` +
            'planter software is older than this page. Restart the ' +
            'greenthumb-api service on the Pi.',
      }
    }
    return data
  } catch (error) {
    return { ok: false, detail: `Could not reach Herman: ${error.message}` }
  }
}

// What a set of step results says about the wiring, once there is enough to
// say anything. Each case names the likeliest single cause.
function diagnose(results) {
  const { full, empty, unplugged } = results
  if (unplugged?.ok && unplugged.wet) {
    return (
      'A loose wire reads wet, so a dead sensor would confirm every dose. ' +
      'printer.cfg still has the old switch_pin: ^PC1. Pull the latest code ' +
      'and re-run the installer, which regenerates it with ^!PC1. If it already ' +
      'says ^!PC1, check that the wire you pulled was the green one.'
    )
  }
  if (!full?.ok || !empty?.ok) return null
  if (!full.wet && empty.wet) {
    return (
      'Reads backwards: wet when empty, dry when full. The SET switch on the ' +
      'adapter board is up. Move it down. Do not fix this by editing ' +
      'switch_pin, which would undo the fail-safe.'
    )
  }
  if (full.wet && empty.wet) {
    return (
      'Reads wet whatever is in the tube. Usually the green and black wires ' +
      'are swapped on the Y-STOP header, which ties the signal pin to ground. ' +
      'Check which pin is GND with a multimeter and swap them.'
    )
  }
  if (!full.wet && !empty.wet) {
    return (
      'Never sees water. Check the red wire has 5V from the Pi (pin 2 or 4), ' +
      'that the sensor is clamped on the falling leg rather than the rising ' +
      'one, and that the tube is no thicker than 13 mm. Also check the tube ' +
      'really was full: the pump has to be running at the moment you check.'
    )
  }
  return null
}

export function WaterSensorPanel() {
  const [live, setLive] = useState(null)
  const [watching, setWatching] = useState(false)
  const [results, setResults] = useState({})
  const [checking, setChecking] = useState('')

  const readLive = async () => setLive(await readSensor())

  // Twenty seconds of one read a second, then it stops itself, the same as the
  // home switch watch. Long enough to start the pump and see the reading move.
  useEffect(() => {
    if (!watching) return undefined
    const poll = setInterval(readLive, 1000)
    const stop = setTimeout(() => setWatching(false), 20000)
    return () => {
      clearInterval(poll)
      clearTimeout(stop)
    }
    // readLive is recreated every render; watching is the only real trigger.
  }, [watching])

  const toggleWatching = () => {
    if (!watching) readLive()
    setWatching((on) => !on)
  }

  const check = async (step) => {
    setChecking(step.key)
    const reading = await readSensor()
    setLive(reading)
    setResults((previous) => ({ ...previous, [step.key]: reading }))
    setChecking('')
  }

  const passed = (step) => {
    const reading = results[step.key]
    return reading?.ok && reading.wet === step.expectWet
  }
  const allPassed = STEPS.every(passed)
  const diagnosis = diagnose(results)
  const enabled = live?.enabled ?? Object.values(results).find((r) => r?.ok)?.enabled

  const resultLine = (step) => {
    const reading = results[step.key]
    if (!reading) return null
    if (!reading.ok) return <p className="field-hint warning">{reading.detail}</p>
    const read = reading.wet ? 'wet' : 'dry'
    const want = step.expectWet ? 'wet' : 'dry'
    return passed(step) ? (
      <p className="field-hint">Pass: read {read}.</p>
    ) : (
      <p className="field-hint warning">
        Fail: read {read}, should read {want}.
      </p>
    )
  }

  return (
    <section className="panel-section">
      <h2>Water sensor</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <div className="slider-row">
            <button type="button" disabled={watching} onClick={readLive}>
              Read sensor
            </button>
            <button type="button" className="primary" onClick={toggleWatching}>
              {watching ? 'Stop watching' : 'Watch for 20s'}
            </button>
            {live?.ok && (
              <span className="position-readout">{live.wet ? 'Wet' : 'Dry'}</span>
            )}
          </div>
          {live ? (
            <p className={live.ok ? 'field-hint' : 'field-hint warning'}>{live.detail}</p>
          ) : (
            <p className="field-hint">
              The liquid sensor clamped on the outlet tube, wired to Y-STOP. It
              reads wet only while water is passing, and dry the rest of the
              time, which is normal. Before checking, set both switches on its
              adapter board down: SET down, output at 3V.
            </p>
          )}
        </div>

        {STEPS.map((step, index) => (
          <div className="field-row" key={step.key}>
            <h3>
              {index + 1}. {step.title}{' '}
              <span className="field-hint">(should read {step.expectWet ? 'wet' : 'dry'})</span>
            </h3>
            <p className="field-hint">{step.how}</p>
            <div className="slider-row">
              <button
                type="button"
                className={checking === step.key ? 'working' : undefined}
                disabled={Boolean(checking)}
                onClick={() => check(step)}
              >
                {checking === step.key ? 'Reading…' : 'Check'}
              </button>
            </div>
            {resultLine(step)}
          </div>
        ))}

        {diagnosis && <p className="field-hint warning">{diagnosis}</p>}

        {allPassed && (
          <p className="field-hint">
            All three checks pass.{' '}
            {enabled
              ? 'Delivery checks are on, so every dose is confirmed.'
              : 'Delivery checks are still off. Set WATER_SENSOR_ENABLED=true in ' +
                '/opt/greenthumb/.env and restart the greenthumb-api service.'}
          </p>
        )}
        {!allPassed && enabled === false && (
          <p className="field-hint">
            Delivery checks are off (WATER_SENSOR_ENABLED=false), so doses are not
            confirmed yet. Turn them on once all three checks pass.
          </p>
        )}

        {Object.keys(results).length > 0 && (
          <div className="field-row">
            <button type="button" disabled={Boolean(checking)} onClick={() => setResults({})}>
              Start over
            </button>
          </div>
        )}
      </div>
    </section>
  )
}
