import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

/**
 * Thin React wrapper around uPlot, whose API is imperative. Keeping the
 * instance in a ref means the rest of the UI never touches it directly.
 */
export function Chart({ data, series, markers = [], height = 320, yRange, yLabel, onCursor }) {
  const containerRef = useRef(null)
  const plotRef = useRef(null)

  // uPlot's own legend is off; the caller draws a compact one and is told
  // which point the cursor is over (null when it leaves). Through a ref for
  // the same reason as the markers: a new callback must not rebuild the plot.
  const onCursorRef = useRef(onCursor)
  useEffect(() => {
    onCursorRef.current = onCursor
  }, [onCursor])

  // Read through a ref inside the draw hook so new waterings repaint without
  // tearing down and rebuilding the whole plot on every fetch. Updated in an
  // effect rather than assigned during render: mutating a ref while rendering
  // is not safe under concurrent rendering, where a render can be discarded.
  // Declared before the setData effect below so the ref is current by the time
  // new data triggers a redraw.
  const markersRef = useRef(markers)
  useEffect(() => {
    markersRef.current = markers
  }, [markers])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return undefined

    const plot = new uPlot(
      {
        width: container.clientWidth || 600,
        height,
        // Timestamps arrive as epoch seconds, which is uPlot's native x format.
        scales: { x: { time: true }, y: yRange ? { range: yRange } : {} },
        legend: { show: false },
        cursor: { drag: { x: true, y: false } },
        axes: [
          {
            stroke: '#8fae9c',
            grid: { stroke: 'rgba(143, 174, 156, 0.12)' },
            // At least this many pixels between time labels. uPlot's default
            // of 50 packed two-line date and time labels edge to edge.
            space: 90,
          },
          {
            stroke: '#8fae9c',
            label: yLabel,
            grid: { stroke: 'rgba(143, 174, 156, 0.12)' },
          },
        ],
        series,
        hooks: {
          setCursor: [(u) => onCursorRef.current?.(u.cursor.idx ?? null)],
          draw: [
            (u) => {
              const { ctx } = u
              ctx.save()
              ctx.lineWidth = 1
              for (const marker of markersRef.current) {
                const x = u.valToPos(marker.t, 'x', true)
                if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) continue
                // A dose the pot's probe never saw arrive is drawn solid
                // amber: it should stand out against the moisture curve that
                // failed to respond to it, because that pairing is the
                // diagnosis.
                if (marker.soak === 'missed') {
                  ctx.strokeStyle = 'rgba(235, 170, 60, 0.9)'
                  ctx.setLineDash([])
                } else {
                  ctx.strokeStyle = 'rgba(125, 200, 255, 0.55)'
                  ctx.setLineDash([4, 3])
                }
                ctx.beginPath()
                ctx.moveTo(x, u.bbox.top)
                ctx.lineTo(x, u.bbox.top + u.bbox.height)
                ctx.stroke()
              }
              ctx.restore()
            },
          ],
        },
      },
      data,
      container,
    )
    plotRef.current = plot

    const observer = new ResizeObserver(() => {
      plot.setSize({ width: container.clientWidth || 600, height })
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      plot.destroy()
      plotRef.current = null
    }
    // Rebuilt only when the plot's shape changes, not when its data does.
    // `data` is read above to seed the plot but is deliberately not a
    // dependency: including it would tear down and recreate uPlot on every
    // poll, losing any zoom or cursor state. The effect below pushes new data
    // into the existing instance instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, height, yRange, yLabel])

  useEffect(() => {
    plotRef.current?.setData(data)
  }, [data])

  return <div className="chart" ref={containerRef} />
}
