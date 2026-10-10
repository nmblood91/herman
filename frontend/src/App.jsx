import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { TopBar } from './components/TopBar'
import { TabBar } from './components/TabBar'
import { ControlsPanel } from './components/ControlsPanel'
import { AutomationPanel } from './components/AutomationPanel'
import { PlantsPanel } from './components/PlantsPanel'
import { PlantEditorPanel } from './components/PlantEditorPanel'
import { SoilPanel } from './components/SoilPanel'
import { HistoryPanel } from './components/HistoryPanel'
import { DiagnosticsPanel } from './components/DiagnosticsPanel'
import { CalibrationPanel } from './components/CalibrationPanel'
import { LedStripPanel } from './components/LedStripPanel'
import { LogsPanel } from './components/LogsPanel'
import './App.css'
import { API_BASE } from './api'

const fetchJson = async (path, options = {}) => {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  const data = await response.json()
  if (!response.ok) {
    throw new Error(data.detail || data.error || 'Request failed')
  }

  return data
}


function App() {
  const [activeTab, setActiveTab] = useState('plants')
  const [overview, setOverview] = useState(null)
  const [plants, setPlants] = useState([])
  // The saved-plant library. Fetched alongside the dashboard because saving a
  // plant changes it, so it has to refresh on the same beat.
  const [profiles, setProfiles] = useState([])
  const [soils, setSoils] = useState([])
  // The band scale, fetched once rather than hard-coded, so the UI cannot
  // drift from greenthumb/moisture.py.
  const [bands, setBands] = useState([])
  // Transient feedback from something the user just did. Clears itself so the
  // bar falls back to the planter's actual state rather than freezing on the
  // last thing that happened to be clicked.
  const [action, setAction] = useState('')
  const actionTimer = useRef(null)

  const setStatus = useCallback((message, { sticky = false } = {}) => {
    clearTimeout(actionTimer.current)
    setAction(message)
    if (!sticky) {
      actionTimer.current = setTimeout(() => setAction(''), 6000)
    }
  }, [])

  useEffect(() => () => clearTimeout(actionTimer.current), [])

  // Motion endpoints answer 200 with {ok: false, error} when Klipper refuses
  // the move, so a successful request is not a successful move.
  const describeResult = (result) =>
    result?.ok === false ? `failed - ${result.error}` : 'ok'

  const loadDashboard = useCallback(async () => {
    try {
      const [overviewData, plantsData, profileData, soilData, bandData] = await Promise.all([
        fetchJson('/overview'),
        fetchJson('/plants'),
        fetchJson('/plant-profiles'),
        fetchJson('/soils'),
        fetchJson('/moisture-bands'),
      ])

      setOverview(overviewData)
      setPlants(plantsData)
      setProfiles(profileData.profiles ?? [])
      setSoils(soilData.soils ?? [])
      setBands(bandData.bands ?? [])
      // Deliberately does not touch `action`. This runs after every action, so
      // writing to the status bar here would wipe the feedback from whatever
      // the user just pressed. The bar falls back to the planter's computed
      // state from overview.system_status on its own once `action` expires.
    } catch (error) {
      setStatus(`Connection failed: ${error.message}`)
    }
    // setStatus is itself a stable useCallback, so this stays stable too and
    // the mount effect below can depend on it honestly rather than
    // suppressing the dependency warning.
  }, [setStatus])

  useEffect(() => {
    // Guarded rather than a bare loadDashboard(): a response that lands after
    // the component is gone would set state on nothing, and setting state
    // straight from an effect body is what the hooks lint objects to.
    let cancelled = false
    async function loadOnMount() {
      if (!cancelled) await loadDashboard()
    }
    loadOnMount()
    return () => {
      cancelled = true
    }
  }, [loadDashboard])

  const systemStatus = overview?.system_status ?? {
    level: 'info',
    message: 'Waking Herman up...',
  }

  const gantryPosition = useMemo(() => {
    const movement = overview?.movement ?? {}
    if (movement.ok === false) return 'unavailable'
    if (!movement.homed) return 'not homed'

    const numericValue = Number(movement.position)
    return Number.isFinite(numericValue) ? `${numericValue} mm` : 'unknown'
  }, [overview])

  const delivery = overview?.delivery
  const deliveryPlant =
    plants.find((item) => item.plant_id === delivery?.last?.plant_id)?.name ??
    delivery?.last?.plant_id

  const homeGantry = async () => {
    try {
      setStatus('Homing gantry...', { sticky: true })
      const result = await fetchJson('/gantry/home', { method: 'POST' })
      setStatus(`Home gantry: ${describeResult(result)}`)
      await loadDashboard()
    } catch (error) {
      setStatus(`Home failed: ${error.message}`)
    }
  }

  const moveGantry = async (distance) => {
    try {
      setStatus(`Moving gantry ${distance} mm...`, { sticky: true })
      const result = await fetchJson('/gantry/move', {
        method: 'POST',
        body: JSON.stringify({ distance_mm: distance }),
      })
      setStatus(`Move gantry ${distance} mm: ${describeResult(result)}`)
      await loadDashboard()
    } catch (error) {
      setStatus(`Move failed: ${error.message}`)
    }
  }

  const moveGantryToEnd = async (end) => {
    try {
      setStatus(`Moving all the way ${end}...`, { sticky: true })
      const result = await fetchJson('/gantry/end', {
        method: 'POST',
        body: JSON.stringify({ end }),
      })
      setStatus(`Move all the way ${end}: ${describeResult(result)}`)
      await loadDashboard()
    } catch (error) {
      setStatus(`Move failed: ${error.message}`)
    }
  }

  const moveToPlant = async (plantId) => {
    try {
      const plant = plants.find((item) => item.plant_id === plantId)
      setStatus(`Moving gantry to ${plant?.name || plantId}...`, { sticky: true })
      const result = await fetchJson(`/plants/${plantId}/move`, { method: 'POST' })
      setStatus(`Move to ${plant?.name || plantId}: ${describeResult(result)}`)
      await loadDashboard()
    } catch (error) {
      setStatus(`Move to plant failed: ${error.message}`)
    }
  }

  const waterPlant = async (plantId) => {
    try {
      const plant = plants.find((item) => item.plant_id === plantId)
      const label = plant?.name || plantId
      // The request does not return until the gantry has moved and the dose has
      // finished, which is over a minute, so say so rather than looking hung.
      setStatus(`Watering ${label}, this takes a minute...`, { sticky: true })
      const result = await fetchJson(`/water/${plantId}`, { method: 'POST' })
      // delivered is null when no outlet sensor is fitted, so only false is a
      // failure — the pump ran and nothing came out the other end.
      const outcome =
        result?.delivered === false
          ? ' but no water reached the outlet — check the reservoir and the line'
          : ''
      setStatus(
        result?.status === 'error'
          ? `Water ${label}: failed - ${result.error}`
          : `Watered ${label} with ${result.volume_ml} mL${outcome}.`,
      )
      await loadDashboard()
    } catch (error) {
      setStatus(`Water failed: ${error.message}`)
    }
  }

  const loadProfile = async (plantId, name) => {
    try {
      setStatus(`Loading ${name}...`, { sticky: true })
      const result = await fetchJson(`/plants/${plantId}/profile/load`, {
        method: 'POST',
        body: JSON.stringify({ name }),
      })
      // Says what was left alone as well as what changed, because that is
      // the surprising half: a saved plant carries care settings, and
      // everything describing the pot itself stays put.
      setStatus(
        `Loaded ${result.name}: waters at ${result.moisture_target}, ` +
          `${result.watering_volume_ml} mL, lights ${result.light_start_time}` +
          `–${result.light_stop_time}. The pot keeps its location ` +
          `(${result.position_mm} mm) and its soil ` +
          `(${result.soil || 'not set'}).`,
      )
      await loadDashboard()
    } catch (error) {
      setStatus(`Load failed: ${error.message}`)
    }
  }

  // 20s of sampling, like the dry calibration. Blocks for the window.
  const measureFieldCapacity = async (plantId) => {
    try {
      setStatus('Measuring field capacity, 20s...', { sticky: true })
      const result = await fetchJson(`/plants/${plantId}/field-capacity`, {
        method: 'POST',
        body: JSON.stringify({ seconds: 20 }),
      })
      setStatus(
        result.written
          ? `Field capacity for this pot is ${result.value}. It now overrides ` +
            'the figure from its mix.'
          : `Not stored — ${result.reason}`,
      )
      await loadDashboard()
    } catch (error) {
      setStatus(`Could not measure: ${error.message}`)
    }
  }

  const clearFieldCapacity = async (plantId) => {
    try {
      const result = await fetchJson(`/plants/${plantId}/field-capacity`, {
        method: 'DELETE',
      })
      setStatus(
        result.field_capacity_source === 'soil'
          ? 'Dropped this pot\'s own figure. It is back to using its mix\'s.'
          : 'Dropped this pot\'s own figure. Its mix has none, so the pot now ' +
            'reads nothing until one is measured.',
      )
      await loadDashboard()
    } catch (error) {
      setStatus(`Could not clear: ${error.message}`)
    }
  }

  // Pot fields only. This used to be nine calls ending in a profile save, so
  // storing a rail coordinate also wrote a saved plant -- the two are edited
  // in separate places now, and this is the pot half.
  const savePot = async (plant) => {
    try {
      setStatus(`Saving ${plant.name}'s pot...`, { sticky: true })

      await fetchJson(`/plants/${plant.plant_id}/position`, {
        method: 'POST',
        body: JSON.stringify({ position_mm: Number(plant.position_mm) }),
      })

      await fetchJson(`/plants/${plant.plant_id}/soil`, {
        method: 'POST',
        body: JSON.stringify({ soil: plant.soil ?? '' }),
      })

      // The span goes before the mode, and the order is not arbitrary:
      // switching a pot to sweep is refused while its span is too narrow to be
      // one, so the span has to be in place first.
      //
      // Sent only when there is a span to send. The default is 0 to 0, which
      // is not a span, and posting it would come back refused and take the
      // rest of the save down with it.
      const low = Number(plant.sweep_min_mm)
      const high = Number(plant.sweep_max_mm)
      if (Number.isFinite(low) && Number.isFinite(high) && low !== high) {
        await fetchJson(`/plants/${plant.plant_id}/sweep`, {
          method: 'POST',
          body: JSON.stringify({ sweep_min_mm: low, sweep_max_mm: high }),
        })
      }

      await fetchJson(`/plants/${plant.plant_id}/watering-mode`, {
        method: 'POST',
        body: JSON.stringify({ watering_mode: plant.watering_mode || 'point' }),
      })

      setStatus(`Saved ${plant.name}'s pot.`)
      await loadDashboard()
    } catch (error) {
      setStatus(`Save failed: ${error.message}`)
    }
  }


  return (
    <div className="app-shell">
      <TopBar />
      <TabBar activeTab={activeTab} onChange={setActiveTab} />
      {/* One line, and it answers "what is my planter doing". Shows feedback
          from something you just did while that is fresh, otherwise the
          planter's own computed state -- never the log, which is a record of
          what was written rather than a description of what is true. */}
      <div className={`status-bar ${action ? '' : `level-${systemStatus.level}`}`}>
        {action || systemStatus.message}
      </div>

      {/* Outside the tabs on purpose. A dose that delivered nothing is the one
          thing that should not be hidden behind whichever tab you are not on.
          Only the last dose is worth reporting: the outlet line is dry between
          waterings by design, so live state says nothing. */}
      {delivery?.enabled && delivery.last && delivery.last.delivered !== true && (
        <div className="status-bar alert">
          {delivery.last.delivered === false
            ? `No water reached the outlet on the last dose (${deliveryPlant}, ${delivery.last.at}). Check the reservoir, then the line for a clog or an airlock.`
            : `Could not verify the last dose (${deliveryPlant}) — the outlet sensor did not respond.`}
        </div>
      )}

      {activeTab === 'plants' && (
        <>
          <PlantsPanel
            plants={plants}
            onSave={savePot}
            status={overview?.plants}
            movement={overview?.movement}
            profiles={profiles}
            onLoadProfile={loadProfile}
            soils={soils}
            onMeasureFieldCapacity={measureFieldCapacity}
            onClearFieldCapacity={clearFieldCapacity}
          />
          {/* Below the cards, because both are libraries the cards pick from:
              a plant and a mix are chosen from dropdowns up there, so editing
              them belongs on the same tab rather than one away. */}
          <PlantEditorPanel
            profiles={profiles}
            bands={bands}
            onRefresh={loadDashboard}
          />
          <SoilPanel soils={soils} plants={plants} onRefresh={loadDashboard} />
        </>
      )}

      {activeTab === 'controls' && (
        <ControlsPanel
          plants={plants}
          gantryPosition={gantryPosition}
          overview={overview}
          onHome={homeGantry}
          onMove={moveGantry}
          onMoveToEnd={moveGantryToEnd}
          onMoveToPlant={moveToPlant}
          onWaterPlant={waterPlant}
          quiet={overview?.quiet}
          onRefresh={loadDashboard}
        />
      )}

      {activeTab === 'automation' && (
        <AutomationPanel overview={overview} onRefresh={loadDashboard} />
      )}

      {/* Checks first, then the three calibrations, then the log. All of these
          fetch their own data, so running one does not reload the rest of the
          dashboard -- which is why they can be mounted side by side here
          rather than nested inside one another as Calibration and Logs were. */}
      {activeTab === 'calibration' && (
        <>
          <DiagnosticsPanel />
          <CalibrationPanel />
          <LedStripPanel overview={overview} />
          <LogsPanel />
        </>
      )}

      {/* Its own tab now. It was below the plant cards, but that tab also
          carries the soil library and the cards themselves, and the chart is
          the thing you consult afterwards rather than act on. */}
      {activeTab === 'history' && <HistoryPanel />}
    </div>
  )

}

export default App
