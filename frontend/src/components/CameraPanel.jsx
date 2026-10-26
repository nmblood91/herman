import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

// The camera's live picture, and nothing else yet.
//
// The stream is one MJPEG response that never ends, and a plain <img> plays it:
// each frame paints over the last. The API starts the camera when the first
// viewer connects and stops it shortly after the last one leaves, so unmounting
// this tab is what lets the camera switch off.
export function CameraPanel() {
  const [camera, setCamera] = useState(null)
  // Bumped to reconnect: a new src makes the browser open a fresh stream.
  const [attempt, setAttempt] = useState(0)
  const [stalled, setStalled] = useState(false)

  useEffect(() => {
    let canceled = false
    async function load() {
      try {
        const response = await fetch(`${API_BASE}/camera`)
        const data = await response.json()
        if (!canceled) setCamera(data)
      } catch (error) {
        if (!canceled) setCamera({ fitted: false, error: `Could not reach Herman: ${error.message}` })
      }
    }
    load()
    return () => {
      canceled = true
    }
  }, [attempt])

  const reconnect = () => {
    setStalled(false)
    setAttempt((count) => count + 1)
  }

  return (
    <section className="panel-section">
      <h2>Camera</h2>

      {camera === null && <p className="field-hint">Looking for the camera…</p>}

      {camera && !camera.fitted && (
        <>
          <p className="field-hint warning">
            {camera.error || 'No camera found. Check the USB camera is plugged into the Pi.'}
          </p>
          <button type="button" onClick={reconnect}>
            Try again
          </button>
        </>
      )}

      {camera?.fitted && (
        <>
          <img
            key={attempt}
            className="camera-feed"
            src={`${API_BASE}/camera/stream?attempt=${attempt}`}
            alt="Live view from the planter's camera"
            onError={() => setStalled(true)}
          />
          {stalled && (
            <p className="field-hint warning">
              The picture stopped. Check the camera is still plugged in, then
              reconnect.
            </p>
          )}
          <div className="slider-row">
            <button type="button" onClick={reconnect}>
              Reconnect
            </button>
          </div>
        </>
      )}
    </section>
  )
}
