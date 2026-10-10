import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../api'

const BLANK = {
  name: '',
  light_start_time: '08:00',
  light_stop_time: '20:00',
  moisture_target: 'dry',
  watering_volume_ml: 100,
  notes: '',
}

// How long Delete has to be held. Long enough that it cannot fire by brushing
// the button, short enough that meaning it does not feel like a chore.
const DELETE_HOLD_MS = 5000

// A ring drawn with a dashed stroke the circle's own circumference long, so
// stroke-dashoffset can reveal it like a clock hand sweeping back rather than
// draw it with canvas or an animation library.
const RING_RADIUS = 8
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS

// The library of saved plants, edited in its own right.
//
// 
// Nothing here touches a pot. A plant becomes real on a pot when you load it
// from that pot's card, which is the same direction the whole pot/plant split
// runs in: this names what a plant wants, the card says where it lives.
export function PlantEditorPanel({ profiles, bands, onRefresh }) {
  // 'new' types a free name below; 'existing' turns that field into a picker
  // over the list. Picked is only ever non-empty in 'existing' mode -- every
  // path back to 'new' clears it, so the two stay in lockstep.
  const [mode, setMode] = useState('new')
  const [picked, setPicked] = useState('')
  const [form, setForm] = useState(BLANK)
  const [message, setMessage] = useState('')

  // 0 while idle, otherwise how far through the hold -- 1 is release the
  // delete. A ref for the frame id and the start time rather than state: both
  // change every frame, and only holdProgress needs to repaint anything.
  const [holdProgress, setHoldProgress] = useState(0)
  const holdFrame = useRef(null)
  const holdStart = useRef(0)

  const stopHold = () => {
    if (holdFrame.current !== null) {
      cancelAnimationFrame(holdFrame.current)
      holdFrame.current = null
    }
    setHoldProgress(0)
  }

  const tickHold = () => {
    // Only ever reached from the requestAnimationFrame loop below, itself
    // only ever started from startHold, itself only ever an event handler --
    // never during render. The lint rule cannot trace that through the
    // recursive rAF callback, the same way it already trusts Date.now()
    // inside a useEffect's setInterval but not a bare closure.
    // eslint-disable-next-line react-hooks/purity
    const fraction = Math.min(1, (performance.now() - holdStart.current) / DELETE_HOLD_MS)
    setHoldProgress(fraction)
    if (fraction >= 1) {
      // Reset before firing: remove() is async, and the ring should not sit
      // at full while the request is in flight or after it fails.
      holdFrame.current = null
      setHoldProgress(0)
      remove()
      return
    }
    holdFrame.current = requestAnimationFrame(tickHold)
  }

  const startHold = () => {
    if (holdFrame.current !== null) return
    // eslint-disable-next-line react-hooks/purity -- see tickHold above
    holdStart.current = performance.now()
    holdFrame.current = requestAnimationFrame(tickHold)
  }

  // A hold in progress belongs to the plant that was picked when it started.
  // If picked changes under it -- there is no ordinary way to do that with
  // one pointer, but a keyboard can tab away mid-hold -- it must not go on to
  // delete whatever is picked by the time the five seconds are up.
  useEffect(() => stopHold, [picked])

  const list = profiles ?? []
  // Very wet is deliberately not offered: a pot is only that just after
  // watering, so targeting it waters on a loop.
  const bandList = (bands ?? []).filter((band) => band.name !== 'very wet')

  // The list already carries every field, so the form fills from the prop
  // rather than fetching the entry again. Synced during render, not in an
  // effect, so the inputs never paint one frame of the previous plant.
  const [syncedPick, setSyncedPick] = useState('')
  if (picked !== syncedPick) {
    setSyncedPick(picked)
    const entry = list.find((profile) => profile.name === picked)
    setForm(
      entry
        ? {
            name: entry.name,
            light_start_time: entry.light_start_time ?? BLANK.light_start_time,
            light_stop_time: entry.light_stop_time ?? BLANK.light_stop_time,
            moisture_target: entry.moisture_target ?? BLANK.moisture_target,
            watering_volume_ml: entry.watering_volume_ml ?? BLANK.watering_volume_ml,
            notes: entry.notes ?? '',
          }
        : BLANK,
    )
  }

  const update = (field, value) => setForm((current) => ({ ...current, [field]: value }))

  // A no-op on the already-active mode, like a tab: clicking New Plant again
  // does not discard a half-typed draft.
  const startNewPlant = () => {
    if (mode === 'new') return
    setMode('new')
    setPicked('')
    setSyncedPick('')
    setForm(BLANK)
    setMessage('')
  }

  const browseSavedPlants = () => {
    if (mode === 'existing') return
    setMode('existing')
    // Picked is always '' on the way in here (startNewPlant clears it, and
    // it starts '' on mount), so the picker opens on its placeholder. Blank
    // the rest too, rather than showing a new-plant draft's leftover fields
    // under a dropdown that says nothing is chosen yet.
    setForm(BLANK)
    setMessage('')
  }

  const save = async () => {
    setMessage('')
    try {
      const response = await fetch(`${API_BASE}/plant-profiles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          watering_volume_ml: Number(form.watering_volume_ml),
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.detail || data.error || `Save failed (HTTP ${response.status})`)
        return
      }
      setMessage(`Saved ${data.name}. Load it onto a pot from that pot's card.`)
      setMode('existing')
      setPicked(data.name)
      setSyncedPick(data.name)
      onRefresh?.()
    } catch (error) {
      setMessage(`Save failed: ${error.message}`)
    }
  }

  const remove = async () => {
    setMessage('')
    try {
      const response = await fetch(`${API_BASE}/plant-profiles/${encodeURIComponent(picked)}`, {
        method: 'DELETE',
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.detail || data.error || `Could not delete ${picked}`)
        return
      }
      // Pots already carrying these settings keep them: loading copied the
      // values across rather than linking to the entry.
      setMessage(`Deleted ${picked}. Pots already loaded with it keep their settings.`)
      setPicked('')
      setSyncedPick('')
      setForm(BLANK)
      onRefresh?.()
    } catch (error) {
      setMessage(`Could not delete ${picked}: ${error.message}`)
    }
  }

  return (
    <section className="panel-section">
      <h2>Plant editor</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <div className="plant-editor-mode">
            <button
              type="button"
              className={mode === 'new' ? 'tab active' : 'tab'}
              onClick={startNewPlant}
            >
              New Plant
            </button>
            <button
              type="button"
              className={mode === 'existing' ? 'tab active' : 'tab'}
              disabled={!list.length}
              onClick={browseSavedPlants}
            >
              Saved Plant
            </button>
          </div>
          {!list.length && (
            <p className="field-hint warning">
              No saved plants. The installer adds a starter set, so this means
              they were all deleted — fill the form below, or put the set back
              with <code>python -m greenthumb.plant_library --install</code> on
              the Pi. A pot takes its care settings by loading one of these, so
              until there is at least one there is nothing to load.
            </p>
          )}
        </div>

        <div className="field-grid">
          {mode === 'existing' ? (
            <label>
              Plant name
              <select
                aria-label="Saved plant to edit"
                value={picked}
                onChange={(event) => setPicked(event.target.value)}
              >
                <option value="">Choose a plant…</option>
                {list.map((profile) => (
                  <option key={profile.name} value={profile.name}>
                    {profile.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label>
              Plant name
              <input
                value={form.name}
                placeholder="Basil"
                onChange={(event) => update('name', event.target.value)}
              />
            </label>
          )}
          <div className="field-pair">
            <label>
              Light start
              <input
                type="time"
                value={form.light_start_time}
                onChange={(event) => update('light_start_time', event.target.value)}
              />
            </label>
            <label>
              Light stop
              <input
                type="time"
                value={form.light_stop_time}
                onChange={(event) => update('light_stop_time', event.target.value)}
              />
            </label>
          </div>
          <label>
            Water when soil is
            <select
              value={form.moisture_target}
              onChange={(event) => update('moisture_target', event.target.value)}
            >
              {bandList.map((band) => (
                <option key={band.name} value={band.name}>
                  {band.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Watering Volume (mL)
            <input
              type="number"
              min="0"
              step="10"
              value={form.watering_volume_ml}
              onChange={(event) => update('watering_volume_ml', event.target.value)}
            />
          </label>
        </div>

        <div className="field-row">
          <label>
            Notes
            <textarea
              rows="3"
              value={form.notes}
              placeholder="Write notes about the plant here"
              onChange={(event) => update('notes', event.target.value)}
            />
          </label>
        </div>

        <div className="field-row">
          <div className="save-delete-row">
            <button
              type="button"
              className="primary group-save-button"
              disabled={!form.name.trim()}
              onClick={save}
            >
              Save plant
            </button>
            {/* Hold rather than click-twice: a slip of the thumb cannot finish
                five seconds by accident, so there is nothing left for a
                second confirmation to catch. Releasing early -- pointer up,
                leaving the button, losing focus -- cancels for free, since
                nothing happens until the hold completes. */}
            {mode === 'existing' && picked && (
              <button
                type="button"
                className={holdProgress > 0 ? 'hold-delete holding' : 'hold-delete'}
                onPointerDown={startHold}
                onPointerUp={stopHold}
                onPointerLeave={stopHold}
                onPointerCancel={stopHold}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') startHold()
                }}
                onKeyUp={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') stopHold()
                }}
                onContextMenu={(event) => event.preventDefault()}
              >
                {holdProgress > 0 && (
                  <svg className="hold-ring" viewBox="0 0 20 20" aria-hidden="true">
                    <circle cx="10" cy="10" r={RING_RADIUS} className="hold-ring-track" />
                    <circle
                      cx="10"
                      cy="10"
                      r={RING_RADIUS}
                      className="hold-ring-fill"
                      style={{
                        strokeDasharray: RING_CIRCUMFERENCE,
                        strokeDashoffset: RING_CIRCUMFERENCE * (1 - holdProgress),
                      }}
                    />
                  </svg>
                )}
                {holdProgress > 0 ? `Deleting ${picked}…` : `Hold to delete ${picked}`}
              </button>
            )}
          </div>
          {message && <p className="field-hint">{message}</p>}
        </div>
      </div>
    </section>
  )
}
