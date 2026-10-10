import { useLayoutEffect, useRef, useState } from 'react'

// A press-and-hold in place of a second confirmation step, for an action
// severe enough to want one but routine enough that a dialog every time
// would train people to click through it without reading. Call onConfirm
// once the hold reaches durationMs; releasing at any point before that --
// pointer up, leaving the button, losing focus -- cancels for free, since
// nothing happens until the hold completes.
//
// Returns `progress` (0 while idle, up to 1 at completion) to draw a ring or
// bar with, `handlers` to spread onto the button -- pointer events for mouse
// and touch together, plus Enter/Space on keydown/keyup for the keyboard --
// and `cancel`, for a caller that needs to call off a hold itself: a hold is
// tied to whatever it was going to confirm, and if that changes identity
// underneath it (the picked row in a list, say), the caller's own effect
// should cancel it rather than let it complete against the new thing.
export function useHoldToConfirm(durationMs, onConfirm) {
  const [progress, setProgress] = useState(0)
  const frame = useRef(null)
  const start = useRef(0)
  // Read from the tick loop through a ref rather than closing over the
  // argument directly: onConfirm is a fresh function every render of the
  // caller, and the loop that started during an earlier render must still
  // call whatever onConfirm is by the time the hold completes. Written in a
  // layout effect rather than during render -- a ref write is a side effect,
  // and render has to stay pure even though this one is harmless in
  // practice. Layout rather than a plain effect so it lands before any event
  // the user causes next, with no gap.
  const onConfirmRef = useRef(onConfirm)
  useLayoutEffect(() => {
    onConfirmRef.current = onConfirm
  })

  const cancel = () => {
    if (frame.current !== null) {
      cancelAnimationFrame(frame.current)
      frame.current = null
    }
    setProgress(0)
  }

  const tick = () => {
    // Only ever reached from the requestAnimationFrame loop below, itself
    // only ever started from begin(), itself only ever an event handler --
    // never during render. The lint rule cannot trace that through the
    // recursive rAF callback, the same way it already trusts Date.now()
    // inside a useEffect's setInterval but not a bare closure.
    // eslint-disable-next-line react-hooks/purity
    const fraction = Math.min(1, (performance.now() - start.current) / durationMs)
    setProgress(fraction)
    if (fraction >= 1) {
      // Reset before firing: onConfirm is typically async, and the ring
      // should not sit at full while that request is in flight or fails.
      frame.current = null
      setProgress(0)
      onConfirmRef.current()
      return
    }
    frame.current = requestAnimationFrame(tick)
  }

  const begin = () => {
    if (frame.current !== null) return
    start.current = performance.now()
    frame.current = requestAnimationFrame(tick)
  }

  const handlers = {
    onPointerDown: begin,
    onPointerUp: cancel,
    onPointerLeave: cancel,
    onPointerCancel: cancel,
    onKeyDown: (event) => {
      if (event.key === 'Enter' || event.key === ' ') begin()
    },
    onKeyUp: (event) => {
      if (event.key === 'Enter' || event.key === ' ') cancel()
    },
    // A real long-press on a touchscreen fires this before it fires
    // onPointerDown's held state is visible, and the OS menu it opens eats
    // the pointerup that would otherwise cancel cleanly.
    onContextMenu: (event) => event.preventDefault(),
  }

  return { progress, handlers, cancel }
}
