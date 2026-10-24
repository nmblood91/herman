import { useState } from 'react'
import { API_BASE } from '../api'

// The motor direction test.
//
// Every unit is wired by hand, and a motor turning the wrong way homes away
// from the switch and into the far end of the rail at homing speed. So nothing
// homes until this has passed: the test turns the motor 10 mm toward the
// switch, before any home, and the person watching says which way it went.
// "Away" flips the direction on the Pi and restarts Klipper, and the test has
// to pass again, because a flip nobody has watched is still a guess.
//
// The status comes from the overview rather than its own fetch, so the
// Controls tab and this card can never disagree about whether it has passed.
export function MotorDirectionPanel({ overview, onRefresh }) {
  const direction = overview?.motor_direction
  const checked = direction?.checked === true
  const testMm = direction?.test_mm ?? 10
  const boardDown = overview?.movement?.ok === false

  const [busy, setBusy] = useState(false)
  // Set once the motor has turned, so the question only appears after
  // there was something to watch.
  const [asking, setAsking] = useState(false)
  const [message, setMessage] = useState(null)

  const post = async (path, body) => {
    setBusy(true)
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body ?? {}),
      })
      const data = await response.json().catch(() => ({}))
      // 409 is the hardware-busy handler: the gantry or pump is in use.
      if (!response.ok || data.ok === false) {
        return { ok: false, error: data.error || `Request failed (HTTP ${response.status})` }
      }
      return { ok: true, ...data }
    } catch (error) {
      return { ok: false, error: `Could not reach Herman: ${error.message}` }
    } finally {
      setBusy(false)
    }
  }

  const release = async () => {
    const result = await post('/gantry/release')
    setMessage(
      result.ok
        ? { tone: 'info', text: 'Motors off. The arm should slide by hand now.' }
        : { tone: 'warning', text: result.error },
    )
  }

  const runTest = async () => {
    setMessage(null)
    const result = await post('/gantry/direction/test')
    if (!result.ok) {
      setAsking(false)
      setMessage({ tone: 'warning', text: result.error })
      return
    }
    setAsking(true)
  }

  const answer = async (towardSwitch) => {
    const result = await post('/gantry/direction/answer', { toward_switch: towardSwitch })
    setAsking(false)
    if (!result.ok) {
      setMessage({ tone: 'warning', text: result.error })
      return
    }
    setMessage(
      towardSwitch
        ? { tone: 'info', text: 'Passed. The arm can home now.' }
        : {
            tone: 'info',
            text:
              'Direction reversed. The motion board is restarting, which takes a few ' +
              'seconds. Then slide the arm back to the middle and test again.',
          },
    )
    onRefresh?.()
  }

  const noMovement = () => {
    setAsking(false)
    setMessage({
      tone: 'warning',
      text:
        "Nothing was changed. Check the motor's cable is plugged in at both ends and " +
        "the planter's power is on, then test again.",
    })
  }

  return (
    <section className="panel-section">
      <h2>Motor direction</h2>

      <div className="general-settings-form">
        <div className="field-row">
          {checked ? (
            <p className="field-hint">
              Tested: the motor turns toward the home switch.
              {direction?.reversed && ' An earlier test reversed its direction.'}
            </p>
          ) : (
            <p className="field-hint warning">
              Not tested yet. The arm won&apos;t home or move until it is.
            </p>
          )}

          <ol className="field-hint">
            <li>
              Slide the arm by hand to the middle of the rail. If it won&apos;t
              slide, press <strong>Release motors</strong>.
            </li>
            <li>
              Press <strong>Turn motor</strong> and watch which way the arm
              moves. It moves {testMm} mm.
            </li>
          </ol>

          <div className="slider-row">
            <button type="button" disabled={busy || boardDown} onClick={release}>
              Release motors
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy || boardDown}
              onClick={runTest}
            >
              {busy && !asking ? 'Turning…' : 'Turn motor'}
            </button>
          </div>

          {boardDown && (
            <p className="field-hint warning">
              The motion board is not responding, so the motor can&apos;t be tested.
            </p>
          )}

          {asking && (
            <>
              <p className="field-hint">Which way did the arm move?</p>
              <div className="slider-row">
                <button
                  type="button"
                  className="primary"
                  disabled={busy}
                  onClick={() => answer(true)}
                >
                  Toward the switch
                </button>
                <button type="button" disabled={busy} onClick={() => answer(false)}>
                  Away from the switch
                </button>
                <button type="button" disabled={busy} onClick={noMovement}>
                  It didn&apos;t move
                </button>
              </div>
            </>
          )}

          {message && (
            <p className={message.tone === 'warning' ? 'field-hint warning' : 'field-hint'}>
              {message.text}
            </p>
          )}
        </div>
      </div>
    </section>
  )
}
