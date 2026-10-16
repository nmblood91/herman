import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

/**
 * Thin React wrapper around uPlot, whose API is imperative. Keeping the
 * instance in a ref means the rest of the UI never touches it directly.
 */
export function Chart({ data, series, markers = [], height = 320, yRange, yLabel }) {
  const containerRef = useRef(null)
  const plotRef = useRef(null)

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
        legend: { live: true },
        cursor: { drag: { x: true, y: false } },
        axes: [
          { stroke: '#8fae9c', grid: { stroke: 'rgba(143, 174, 156, 0.12)' } },
          {
            stroke: '#8fae9c',
            label: yLabel,
            grid: { stroke: 'rgba(143, 174, 156, 0.12)' },
          },
        ],
        series,
        hooks: {
          draw: [
            (u) => {
              const { ctx } = u
              ctx.save()
              ctx.lineWidth = 1
              for (const marker of markersRef.current) {
                const x = u.valToPos(marker.t, 'x', true)
                if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) continue
                // A dose that delivered nothing is drawn solid red: it should
                // stand out against the moisture curve that failed to respond
                // to it, because that pairing is the whole diagnosis.
                if (marker.delivered === false) {
                  ctx.strokeStyle = 'rgba(230, 90, 80, 0.85)'
                  ctx.setLineDash([])
                } else if (marker.soak === 'missed') {
                  // Left the tube, or was never checked there, but the pot's
                  // probe never saw it arrive: amber, a step short of red.
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
