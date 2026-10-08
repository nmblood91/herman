import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE } from '../api'

// The <img> is the whole player. Browsers hold a multipart/x-mixed-replace
// response open and paint each part over the last, which is why live video
// here needs no player library and no WebSocket.
//
// The same behaviour is why there is a Reconnect button. When the stream ends
// -- the capture stalled, or the Pi was rebooted -- the browser leaves the last
// frame on screen rather than firing an error, so a dead stream looks exactly
// like a very still plant. Reconnect changes the URL, because pointing an <img>
// at a URL it has already loaded will not reopen the connection.

export function CameraPanel() {
  const [status, setStatus] = useState(null)
  const [attempt, setAttempt] = useState(1)
  const [failed, setFailed] = useState(false)
  const imageRef = useRef(null)

  const loadStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/camera`)
      setStatus(await response.json())
    } catch (error) {
      setStatus({ fitted: false, error: `Could not reach Herman: ${error.message}` })
    }
  }, [])

  useEffect(() => {
    loadStatus()
  }, [loadStatus, attempt])

  // Dropping the src on the way out is what actually closes the connection, and
  // closing it is what lets the capture stop and release the camera. Without
  // this the browser can hold the request open after the tab is switched away,
  // and the camera stays busy with nobody watching.
  useEffect(() => {
    const image = imageRef.current
    return () => {
      if (image) image.src = ''
    }
  }, [attempt])

  const reconnect = () => {
    setFailed(false)
    setAttempt((value) => value + 1)
  }

  const fitted = status?.fitted !== false

  return (
    <section className="panel-section">
      <h2>Camera</h2>
      <p className="field-hint">
        A live view for checking on the plants and for aiming the camera. It is
        not recorded, and nothing leaves your network.
      </p>

      {!fitted ? (
        <div className="camera-frame camera-frame-empty">
          <p>No camera detected.</p>
          <p className="field-hint">
            {status?.error ||
              'Check that the ribbon cable is seated at both ends, with the contacts facing the right way.'}
          </p>
        </div>
      ) : (
        <>
          <div className="camera-frame">
            <img
              ref={imageRef}
              key={attempt}
              src={`${API_BASE}/camera/stream?view=${attempt}`}
              alt="Live view of the planter"
              onError={() => setFailed(true)}
            />
          </div>

          {failed && (
            <p className="field-hint warning">
              The stream stopped. Reconnect to start the camera again.
            </p>
          )}

          <div className="camera-actions">
            <button type="button" className="primary" onClick={reconnect}>
              Reconnect
            </button>
            {status && (
              <span className="field-hint">
                {status.width}&times;{status.height} at {status.fps} fps
                {status.error ? ` — ${status.error}` : ''}
              </span>
            )}
          </div>
        </>
      )}
    </section>
  )
}
