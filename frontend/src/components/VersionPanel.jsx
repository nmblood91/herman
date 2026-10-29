import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

// What is running: the release, the commit the API process started from, and
// the commit this page was built from. The two warnings are the point -- a
// pull without a restart, and a pull without a frontend rebuild, both look
// like features that do not work.
export function VersionPanel() {
  const [build, setBuild] = useState(null)

  useEffect(() => {
    let canceled = false
    async function readVersion() {
      try {
        const response = await fetch(`${API_BASE}/version`)
        if (!response.ok || canceled) return
        setBuild(await response.json())
      } catch {
        // Leaves the panel without a version rather than breaking it.
      }
    }
    readVersion()
    return () => {
      canceled = true
    }
  }, [])

  return (
    <section className="panel-section">
      <h2>Software</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <p className="field-hint">
            Version {build?.version ?? '—'} · API {build?.running_commit ?? '—'} ·
            page {__BUILD_COMMIT__}
          </p>
          {build?.klipper?.host && (
            <p className="field-hint">
              Klipper {build.klipper.host} · SKR firmware {build.klipper.mcu ?? 'not connected'}
            </p>
          )}
          {build?.klipper?.firmware_mismatch && (
            <p className="field-hint warning">
              The SKR&apos;s firmware ({build.klipper.mcu}) was built from a
              different Klipper than the one on the Pi ({build.klipper.host}).
              The gantry and pump may stop responding. Flash
              your board&apos;s firmware from deploy/klipper (from an SD card
              for an SKR Mini E3, the Boot jumper and USB for an SKR Pico), or
              re-run the installer to put the Pi back on the pinned Klipper.
            </p>
          )}
          {build?.stale && (
            <p className="field-hint warning">
              The planter has newer code on disk ({build.checkout_commit}) than
              the service is running ({build.running_commit}). Something was
              pulled without restarting. Run{' '}
              <code>sudo systemctl restart greenthumb-api</code> on the Pi.
            </p>
          )}
          {build?.running_commit &&
            __BUILD_COMMIT__ !== 'unknown' &&
            build.running_commit !== __BUILD_COMMIT__ && (
              <p className="field-hint warning">
                This page was built from {__BUILD_COMMIT__} but the API is
                running {build.running_commit}. Rebuild the frontend, or you
                will hit features the API does not have.
              </p>
            )}
        </div>
      </div>
    </section>
  )
}
