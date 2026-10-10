import { useEffect, useState } from 'react'
import { API_BASE } from '../api'
import { useHoldToConfirm } from '../useHoldToConfirm'
import { HoldRing } from './HoldRing'

// The soil library, on the same tab as the pots that use it.
//
// Takes `soils` as a prop rather than fetching its own copy. It used to live in
// Settings, a tab away from the plant cards, and self-fetched a second list
// that the dashboard was already holding for the soil dropdown -- so the two
// could disagree until something reloaded.
const SAMPLE_SECONDS = 20

// How long Delete has to be held. Matches the plant editor's.
const DELETE_HOLD_MS = 5000

const BLANK = { name: '', capacity: '', wilting: '', notes: '' }

export function SoilPanel({ soils, plants, onRefresh }) {
  // 'new' types a free name below; 'existing' turns that field into a picker
  // over the list. Picked is only ever non-empty in 'existing' mode -- every
  // path back to 'new' clears it, so the two stay in lockstep. Same split as
  // the plant editor, and for the same reason: there was no way to edit an
  // existing mix's figures short of retyping its name exactly and hoping the
  // overwrite landed on the right one.
  const [mode, setMode] = useState('new')
  const [picked, setPicked] = useState('')
  const [form, setForm] = useState(BLANK)
  const [message, setMessage] = useState('')

  // Which probe each mix will be measured with. One figure per mix is enough:
  // probes of the same kind read closely enough that a good reading from any
  // of them beats four nobody got round to taking. A pot that wants better
  // measures its own, on its card. Per-list-item rather than part of the
  // edit form below: measuring is a hardware action against whichever mix
  // needs it, not a field you fill in and save.
  const [probe, setProbe] = useState({})
  const [measuring, setMeasuring] = useState('')

  const list = soils ?? []
  const pots = plants ?? []

  // The list already carries every field, so the form fills from the prop
  // rather than fetching the entry again. Synced during render, not in an
  // effect, so the inputs never paint one frame of the previous mix.
  const [syncedPick, setSyncedPick] = useState('')
  if (picked !== syncedPick) {
    setSyncedPick(picked)
    const entry = list.find((soil) => soil.name === picked)
    setForm(
      entry
        ? {
            name: entry.name,
            capacity: String(entry.field_capacity_vwc ?? ''),
            wilting: String(entry.wilting_point_vwc ?? ''),
            notes: entry.notes ?? '',
          }
        : BLANK,
    )
  }

  const update = (field, value) => setForm((current) => ({ ...current, [field]: value }))

  // A no-op on the already-active mode, like a tab: clicking New Soil again
  // does not discard a half-typed draft.
  const startNewSoil = () => {
    if (mode === 'new') return
    setMode('new')
    setPicked('')
    setSyncedPick('')
    setForm(BLANK)
    setMessage('')
  }

  const browseSavedSoils = () => {
    if (mode === 'existing') return
    setMode('existing')
    // Picked is always '' on the way in here, so the picker opens on its
    // placeholder. Blank the rest too, rather than showing a new-mix draft's
    // leftover fields under a dropdown that says nothing is chosen yet.
    setForm(BLANK)
    setMessage('')
  }

  const measure = async (soilName) => {
    const plantId = probe[soilName] || pots[0]?.plant_id
    if (!plantId) return
    setMessage('')
    setMeasuring(soilName)
    try {
      const response = await fetch(
        `${API_BASE}/soils/${encodeURIComponent(soilName)}/field-capacity`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plant_id: plantId, seconds: SAMPLE_SECONDS }),
        },
      )
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(
          data.detail || data.error || `Could not measure (HTTP ${response.status})`,
        )
        return
      }
      if (!data.written) {
        setMessage(`Not stored — ${data.reason}`)
        return
      }
      const applied = data.inherited_by ?? []
      setMessage(
        `${soilName} reads ${data.value} at field capacity, measured with ` +
          `${data.measured_with}. ` +
          (applied.length
            ? `Applied to ${applied.join(', ')}.`
            : 'No pot is filled with it yet, so nothing changed.'),
      )
      onRefresh?.()
    } catch (error) {
      setMessage(`Could not measure: ${error.message}`)
    } finally {
      setMeasuring('')
    }
  }

  const save = async () => {
    setMessage('')
    try {
      const response = await fetch(`${API_BASE}/soils`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name,
          field_capacity_vwc: Number(form.capacity),
          wilting_point_vwc: Number(form.wilting),
          notes: form.notes,
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.detail || data.error || `Save failed (HTTP ${response.status})`)
        return
      }
      setMessage(
        `Saved ${data.name}: ${data.available_points} points of usable water, ` +
          `wilting at ${Math.round((data.wilting_fraction ?? 0) * 100)}% of field capacity.`,
      )
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
      const response = await fetch(`${API_BASE}/soils/${encodeURIComponent(picked)}`, {
        method: 'DELETE',
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.detail || data.error || `Could not remove ${picked}`)
        return
      }
      // Pots still naming it keep the name, which stops resolving. Saying so
      // is the point -- a silently cleared soil hides that a pot is no longer
      // described, and a pot with no soil is never watered automatically.
      setMessage(`Removed ${picked}. Any pot still set to it needs a new soil.`)
      setPicked('')
      setSyncedPick('')
      setForm(BLANK)
      onRefresh?.()
    } catch (error) {
      setMessage(`Could not remove ${picked}: ${error.message}`)
    }
  }

  const { progress: holdProgress, handlers: holdHandlers, cancel: cancelHold } =
    useHoldToConfirm(DELETE_HOLD_MS, remove)

  // A hold in progress belongs to the mix that was picked when it started.
  // If picked changes under it -- there is no ordinary way to do that with
  // one pointer, but a keyboard can tab away mid-hold -- it must not go on to
  // remove whatever is picked by the time the five seconds are up.
  //
  // cancelHold deliberately left out of the deps: it is a fresh closure every
  // render (the hook does not memoise it), so including it would re-fire this
  // effect on every render -- which, while a hold is in progress, is every
  // animation frame, cancelling the hold the instant it ticks.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => cancelHold, [picked])

  const formReady = form.name.trim() && form.capacity !== '' && form.wilting !== ''

  return (
    <section className="panel-section">
      <h2>Soil</h2>

      <div className="general-settings-form">
        <div className="field-row">
          {list.length ? (
            <ul className="soil-list">
              {list.map((soil) => (
                <li key={soil.name}>
                  <span>
                    <strong>{soil.name}</strong>
                    <small>
                      field capacity {soil.field_capacity_vwc}% &middot; wilting{' '}
                      {soil.wilting_point_vwc}% &middot; {soil.available_points} pts usable
                    </small>
                    {soil.field_capacity_raw != null ? (
                      <small>
                        reads {soil.field_capacity_raw} at field capacity
                        {soil.field_capacity_measured_at
                          ? `, measured ${soil.field_capacity_measured_at.slice(0, 10)}`
                          : ''}
                      </small>
                    ) : (
                      <small className="warning">
                        not measured — pots of this mix read nothing and are never
                        watered automatically
                      </small>
                    )}
                    {soil.notes && <small>{soil.notes}</small>}
                    <span className="soil-capacity">
                      <select
                        aria-label={`Probe to measure ${soil.name} with`}
                        value={probe[soil.name] ?? pots[0]?.plant_id ?? ''}
                        onChange={(event) =>
                          setProbe((current) => ({
                            ...current,
                            [soil.name]: event.target.value,
                          }))
                        }
                      >
                        {pots.map((pot) => (
                          <option key={pot.plant_id} value={pot.plant_id}>
                            {pot.name}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={Boolean(measuring) || !pots.length}
                        onClick={() => measure(soil.name)}
                      >
                        {measuring === soil.name
                          ? 'Measuring…'
                          : 'Measure field capacity'}
                      </button>
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="field-hint warning">
              No mixes. The installer adds a starting set, so this means they
              were all removed — add your own below, or put the set back with{' '}
              <code>python -m greenthumb.soil_library --install</code> on the
              Pi. Until a pot has a soil it is never watered automatically.
            </p>
          )}
        </div>

        <div className="field-row">
          <div className="plant-editor-mode">
            <button
              type="button"
              className={mode === 'new' ? 'tab active' : 'tab'}
              onClick={startNewSoil}
            >
              New Soil
            </button>
            <button
              type="button"
              className={mode === 'existing' ? 'tab active' : 'tab'}
              disabled={!list.length}
              onClick={browseSavedSoils}
            >
              Saved Soil
            </button>
          </div>
        </div>

        <div className="field-row">
          <div className="soil-form">
            {mode === 'existing' ? (
              <label>
                Name
                <select
                  aria-label="Saved mix to edit"
                  value={picked}
                  onChange={(event) => setPicked(event.target.value)}
                >
                  <option value="">Choose a mix…</option>
                  {list.map((soil) => (
                    <option key={soil.name} value={soil.name}>
                      {soil.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <label>
                Name
                <input
                  value={form.name}
                  placeholder="My potting mix"
                  onChange={(event) => update('name', event.target.value)}
                />
              </label>
            )}
            <label>
              Field capacity (% VWC)
              <input
                type="number"
                min="1"
                max="100"
                value={form.capacity}
                onChange={(event) => update('capacity', event.target.value)}
              />
            </label>
            <label>
              Wilting point (% VWC)
              <input
                type="number"
                min="1"
                max="100"
                value={form.wilting}
                onChange={(event) => update('wilting', event.target.value)}
              />
            </label>
          </div>
        </div>

        <div className="field-row">
          <label>
            Notes
            <textarea
              rows="3"
              value={form.notes}
              placeholder="Where these figures came from."
              onChange={(event) => update('notes', event.target.value)}
            />
          </label>
        </div>

        <div className="field-row">
          <div className="save-delete-row">
            <button
              type="button"
              className="primary group-save-button"
              disabled={!formReady}
              onClick={save}
            >
              Save soil
            </button>
            {/* Hold rather than an inline Remove on every row: one place to
                delete a mix, same as a saved plant, and a slip of the thumb
                cannot finish five seconds by accident. */}
            {mode === 'existing' && picked && (
              <button
                type="button"
                className={holdProgress > 0 ? 'hold-delete holding' : 'hold-delete'}
                {...holdHandlers}
              >
                <HoldRing progress={holdProgress} />
                {holdProgress > 0 ? `Removing ${picked}…` : `Hold to remove ${picked}`}
              </button>
            )}
          </div>
          {message && <p className="field-hint">{message}</p>}
        </div>

        <div className="field-row">
          <p className="field-hint">
            The percentages do not convert into sensor readings, which is why
            each mix also needs <strong>field capacity measured once</strong>,
            above. Soak a pot of it through, let it drain 24 hours, pick the
            probe sitting in that pot, and measure. That figure is copied onto
            every pot filled with the mix, and gives the top of their scale.
            Re-measure after a repot: mixes lose capacity as they age and
            compact.
          </p>
          <p className="field-hint">
            To measure your own: weigh the pot soaked and drained 24 hours,
            then again bone dry, and the difference is the water it holds.
            Bagged mixes vary by manufacturer and by how firmly they were
            packed, and they lose capacity as they age and compact — so a
            measured mix beats a looked-up one.
          </p>
        </div>
      </div>
    </section>
  )
}
