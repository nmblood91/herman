# GreenThumb web UI

React + Vite single-page app. It is the control surface for the planter: plant
moisture and watering, gantry jogging, lighting, history charts, sensor
calibration and settings.
It talks to the FastAPI backend under `/api/v1`.

## Layout

- `src/App.jsx` — tab shell and shared state
- `src/components/TopBar.jsx` — header
- `src/components/TabBar.jsx` — tab switching

Four tabs, one component each unless noted:

| Tab | Components |
|---|---|
| Controls | `ControlsPanel.jsx` — gantry homing and jogging, dances, move-to-plant, water-a-plant, lighting, pump |
| Plants | `PlantsPanel.jsx` — per-plant current moisture, plus an expandable settings form for name, light window, target, dose volume and rail position |
| Sensors | `HistoryPanel.jsx` + `Chart.jsx` for the chart, `CalibrationPanel.jsx` for per-sensor calibration |
| Settings | `SettingsPanel.jsx` — automatic watering, idle motion, quiet hours, LED strip type and colour order, planter clock; `LogsPanel.jsx` renders below it |

## Local development

```bash
npm install
npm run dev
```

`vite.config.js` proxies `/api` to `http://localhost:8000`, so run the backend on
the same machine. To develop against the Pi instead, point that proxy target at
`http://herman.local:8000`.

## Build output is not committed

`npm run build` writes `dist/`, which is gitignored. On the Pi, nginx serves
`/opt/greenthumb/frontend/dist` and
[deploy/pi/install-green-thumb.sh](../deploy/pi/install-green-thumb.sh) builds it
during the install.

Keep it that way. Committed build output means every install on the Pi
rewrites tracked files and leaves the checkout dirty, so the next `git pull`
refuses to merge. Build output belongs to the machine that serves it.

**So a frontend change needs a build on the Pi, not just a `git pull`** — re-run
the install script, or `cd /opt/greenthumb/frontend && npm run build`.

## Lockfile

`npm install` on the Pi rewrites `package-lock.json`, because the committed
lockfile is generated on Windows and lacks the ARM Rollup binary. The install
script checks the file back out afterwards so the churn does not dirty the
checkout. That is also why it uses `npm install` rather than `npm ci`.
