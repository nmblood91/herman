import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { TopBar } from './components/TopBar'
import { TabBar } from './components/TabBar'
import { ControlsPanel } from './components/ControlsPanel'
import { SettingsPanel } from './components/SettingsPanel'
import { CalibrationPanel } from './components/CalibrationPanel'
import { PlantsPanel } from './components/PlantsPanel'
import { LogsPanel } from './components/LogsPanel'
import { HistoryPanel } from './components/HistoryPanel'
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
  const [activeTab, setActiveTab] = useState('controls')
  const [overview, setOverview] = useState(null)
  const [plants, setPlants] = useState([])
  const [logs, setLogs] = useState([])
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
      const [overviewData, plantsData, logsData] = await Promise.all([
        fetchJson('/overview'),
        fetchJson('/plants'),
        fetchJson('/logs?lines=20'),
      ])

      setOverview(overviewData)
      setPlants(plantsData)
      setLogs(logsData)
      // Deliberately does not touch `action` here. The status bar shows the
      // planter's computed state from overview.system_status; this used to
      // overwrite it with logsData[0], the newest raw log line, timestamp and
      // level included -- and since this runs after every action, it also
      // wiped the feedback from whatever the user had just done.
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

  const savePlant = async (plant) => {
    try {
      setStatus(`Saving ${plant.name}...`, { sticky: true })

      await fetchJson(`/plants/${plant.plant_id}/name`, {
        method: 'POST',
        body: JSON.stringify({ name: plant.name }),
      })

      await fetchJson(`/plants/${plant.plant_id}/lighting`, {
        method: 'POST',
        body: JSON.stringify({
          start_time: plant.light_start_time,
          stop_time: plant.light_stop_time,
        }),
      })

      await fetchJson(`/plants/${plant.plant_id}/moisture`, {
        method: 'POST',
        body: JSON.stringify({ moisture_target: Number(plant.moisture_target) }),
      })

      await fetchJson(`/plants/${plant.plant_id}/volume`, {
        method: 'POST',
        body: JSON.stringify({ watering_volume_ml: Number(plant.watering_volume_ml) }),
      })

      await fetchJson(`/plants/${plant.plant_id}/position`, {
        method: 'POST',
        body: JSON.stringify({ position_mm: Number(plant.position_mm) }),
      })

      setStatus(`Saved ${plant.name}.`)
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

      {activeTab === 'controls' && (
        <ControlsPanel
          plants={plants}
          gantryPosition={gantryPosition}
          overview={overview}
          onHome={homeGantry}
          onMove={moveGantry}
          onMoveToPlant={moveToPlant}
          onWaterPlant={waterPlant}
          quiet={overview?.quiet}
          onQuietChange={loadDashboard}
        />
      )}

      {activeTab === 'plants' && (
        <PlantsPanel
          plants={plants}
          onSave={savePlant}
          status={overview?.plants}
          movement={overview?.movement}
        />
      )}

      {activeTab === 'sensors' && (
        <>
          {/* Both fetch their own data, so changing a range or running a
              calibration does not reload the whole dashboard. */}
          <HistoryPanel />
          <CalibrationPanel />
        </>
      )}

      {activeTab === 'settings' && (
        <>
          <SettingsPanel overview={overview} onQuietChange={loadDashboard} />
          <LogsPanel logs={logs} />
        </>
      )}
    </div>
  )

}

export default App
