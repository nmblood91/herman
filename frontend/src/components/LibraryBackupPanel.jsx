import { useRef, useState } from 'react'
import { API_BASE } from '../api'

// Saves the soil and plant profile libraries to a JSON file on this device,
// and loads one back. A reflashed Pi starts from the built-in libraries; this
// is how measured field capacities and tuned plants survive it.
export function LibraryBackupPanel({ onRefresh }) {
  const [replace, setReplace] = useState(false)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [skipped, setSkipped] = useState([])
  const fileInput = useRef(null)

  const download = async () => {
    setBusy('export')
    setMessage('')
    setSkipped([])
    try {
      const response = await fetch(`${API_BASE}/library/export`)
      if (!response.ok) {
        setMessage(`Backup failed (HTTP ${response.status})`)
        return
      }
      const data = await response.json()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `greenthumb-library-${data.exported_at.slice(0, 10)}.json`
      link.click()
      URL.revokeObjectURL(url)
      const soils = Object.keys(data.soil_profiles ?? {}).length
      const plants = Object.keys(data.plant_profiles ?? {}).length
      setMessage(`Saved ${soils} soil profiles and ${plants} plant profiles.`)
    } catch (error) {
      setMessage(`Backup failed: ${error.message}`)
    } finally {
      setBusy('')
    }
  }

  const upload = async (event) => {
    const file = event.target.files?.[0]
    // Cleared so picking the same file again still fires a change.
    event.target.value = ''
    if (!file) return
    setBusy('import')
    setMessage('')
    setSkipped([])
    try {
      let backup
      try {
        backup = JSON.parse(await file.text())
      } catch {
        setMessage(`${file.name} is not a JSON file.`)
        return
      }
      const response = await fetch(`${API_BASE}/library/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backup, replace }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.error || data.detail || `Restore failed (HTTP ${response.status})`)
        return
      }
      const count = (section, outcome) =>
        Object.values(data[section]).filter((value) => value === outcome).length
      const problems = ['soil_profiles', 'plant_profiles'].flatMap((section) =>
        Object.entries(data[section])
          .filter(([, value]) => value.startsWith('skipped'))
          .map(([name, value]) => `${name}: ${value.replace(/^skipped: /, '')}`),
      )
      const kept = count('soil_profiles', 'kept') + count('plant_profiles', 'kept')
      setMessage(
        `Restored ${count('soil_profiles', 'written')} soil profiles and ` +
          `${count('plant_profiles', 'written')} plant profiles.` +
          (kept ? ` Kept ${kept} you already had.` : '') +
          (problems.length ? ` Skipped ${problems.length}:` : ''),
      )
      setSkipped(problems)
      onRefresh?.()
    } catch (error) {
      setMessage(`Restore failed: ${error.message}`)
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="panel-section">
      <h2>Back up profiles</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <p className="field-hint">Keep a copy before reflashing the Pi.</p>
          <div className="slider-row">
            <button type="button" disabled={Boolean(busy)} onClick={download}>
              {busy === 'export' ? 'Saving…' : 'Download backup'}
            </button>
          </div>
        </div>

        <div className="field-row">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={replace}
              onChange={(event) => setReplace(event.target.checked)}
            />
            Replace profiles with the same name
          </label>
          <p className="field-hint">
            {replace
              ? 'Profiles in the file overwrite ones here with the same name.'
              : 'Profiles you already have are left alone; only ones missing here are added.'}{' '}
            Soil profiles and plant profiles that are not in the file are
            never removed. A planter&apos;s data/state.json works here too.
          </p>
          <div className="slider-row">
            <button
              type="button"
              disabled={Boolean(busy)}
              onClick={() => fileInput.current?.click()}
            >
              {busy === 'import' ? 'Restoring…' : 'Restore from file'}
            </button>
            <input
              ref={fileInput}
              type="file"
              accept="application/json,.json"
              hidden
              onChange={upload}
            />
          </div>
        </div>

        {message && <p className="field-hint warning">{message}</p>}
        {skipped.map((line) => (
          <p className="field-hint warning" key={line}>
            {line}
          </p>
        ))}
      </div>
    </section>
  )
}
