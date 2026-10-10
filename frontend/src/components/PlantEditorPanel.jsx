import { useState } from 'react'
import { API_BASE } from '../api'

const BLANK = {
  name: '',
  light_start_time: '08:00',
  light_stop_time: '20:00',
  moisture_target: 'dry',
  watering_volume_ml: 100,
  notes: '',
}

// The library of saved plants, edited in its own right.
//
// Until this existed the only way to write a saved plant was to snapshot a
// pot, so fixing one meant loading it onto a spare pot, editing, and saving
// back -- changing what the planter is actually running in order to edit
// something it is not.
//
// Nothing here touches a pot. A plant becomes real on a pot when you load it
// from that pot's card, which is the same direction the whole pot/plant split
// runs in: this names what a plant wants, the card says where it lives.
export function PlantEditorPanel({ profiles, bands, onRefresh }) {
  const [picked, setPicked] = useState('')
  const [form, setForm] = useState(BLANK)
  const [message, setMessage] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)

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
    setConfirmDelete(false)
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
      // Renaming writes a new entry rather than moving the old one, because
      // the name is the key. Saying so beats leaving someone to find the
      // original still in the list.
      const renamed = picked && picked !== data.name
      setMessage(
        renamed
          ? `Saved ${data.name}. ${picked} is still there — the name is the key, ` +
            'so this made a second plant rather than renaming the first.'
          : `Saved ${data.name}. Load it onto a pot from that pot's card.`,
      )
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
          <div className="load-profile-row">
            <select
              aria-label="Saved plant to edit"
              value={picked}
              onChange={(event) => setPicked(event.target.value)}
            >
              <option value="">
                {list.length ? 'New plant…' : 'No saved plants yet — add one below'}
              </option>
              {list.map((profile) => (
                <option key={profile.name} value={profile.name}>
                  {profile.name}
                </option>
              ))}
            </select>
            {picked && !confirmDelete && (
              <button type="button" onClick={() => setConfirmDelete(true)}>
                Delete
              </button>
            )}
            {picked && confirmDelete && (
              <>
                <button type="button" onClick={remove}>
                  Delete {picked}
                </button>
                <button type="button" onClick={() => setConfirmDelete(false)}>
                  Cancel
                </button>
              </>
            )}
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
          <label>
            Plant name
            <input
              value={form.name}
              placeholder="Basil"
              onChange={(event) => update('name', event.target.value)}
            />
          </label>
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
          <label>
            Water when it reaches
            <select
              value={form.moisture_target}
              onChange={(event) => update('moisture_target', event.target.value)}
            >
              {bandList.map((band) => (
                <option key={band.name} value={band.name}>
                  {band.name}
                  {band.description ? ` — ${band.description}` : ''}
                </option>
              ))}
            </select>
          </label>
          <label>
            Watering volume (mL)
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
              placeholder="Why this plant is set up this way."
              onChange={(event) => update('notes', event.target.value)}
            />
          </label>
          <p className="field-hint">
            The only field here the planter never acts on. The rest say what it
            does; this says why, for whoever reads it next — including you in a
            season's time.
          </p>
        </div>

        <div className="field-row">
          <button
            type="button"
            className="primary group-save-button"
            disabled={!form.name.trim()}
            onClick={save}
          >
            Save plant
          </button>
          {message && <p className="field-hint">{message}</p>}
          <p className="field-hint">
            The name is the key, so saving replaces any plant of that name
            rather than making a second one. Nothing here changes a pot —
            load the plant from a pot's card for that.
          </p>
        </div>
      </div>
    </section>
  )
}
