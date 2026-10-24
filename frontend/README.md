# GreenThumb web UI

React + Vite single-page app. It is the control surface for the planter: pot
moisture and watering, the plant and soil libraries, gantry jogging, lighting,
automation, calibration and history charts.
It talks to the FastAPI backend under `/api/v1`.

## Layout

- `src/App.jsx` — tab shell and shared state
- `src/components/TopBar.jsx` — header
- `src/components/TabBar.jsx` — tab switching

Six tabs, in the order `TabBar.jsx` lists them. There is no Settings tab: each
of its groups now sits with the thing it governs.

| Tab | Components |
|---|---|
| Plants and Soil | `PlantsPanel.jsx` — a card per pot, with its moisture and an expandable form for the pot's mix, rail position and watering mode, and its Zone Schedule light color (`PotLightColor.jsx`); `PlantEditorPanel.jsx` — the plant-profile library; `SoilPanel.jsx` — the soil library. Both libraries sit below the cards, which pick from them |
| Controls | `ControlsPanel.jsx` — gantry homing and jogging, dances, move-to-plant, water-a-plant, lighting, quiet snooze |
| Automation | `AutomationPanel.jsx` — automatic watering, homing (startup home, hourly auto-patrol), quiet hours |
| Calibration | `HomeSwitchPanel.jsx` (endstop test), `MotorDirectionPanel.jsx` (motor direction test, which unlocks homing), `PumpPanel.jsx` (pump flow rate), `CalibrationPanel.jsx` (the probes’ air reading, a health check), `LedStripPanel.jsx` (strip type and color order), `ClockPanel.jsx` (planter clock and time zone), `VersionPanel.jsx` (running and built commits), `LogsPanel.jsx`, mounted side by side |
| History | `HistoryPanel.jsx` + `Chart.jsx` |
| Help | `HelpPanel.jsx` — the owner's guide, one long page with a contents box |

### Editing the Help guide

The guide is plain Markdown in `src/help/`, one file per tab plus a glossary,
written for owners with no technical background. Edit a file and nothing else:
VS Code's Markdown preview shows the result, and `npm run dev` shows it in the
app. `src/help/pages.js` sets the order, so a new file needs a line there.

- Each file starts with `## ` and the tab's name; each `### ` heading becomes
  an entry in the contents box.
- Link to any heading with `[text](#heading-name)`: the heading in lower case,
  punctuation dropped, spaces as dashes. A repeated heading gets `-1`, `-2` in
  page order.
- Name a button as **bold** after "press", "choose" or "hold", using its exact
  label.

`tests/test_help.py` fails if a link points at no heading, if a named button
does not exist in the app, or if a tab has no section. The guide is built into
the app, so an edit reaches a planter like any other change: pull, then re-run
the installer.

The moisture scale is not here: field capacity and wilting point are sensor
readings on each soil profile, set on the Plants and Soil tab.

## Local development

```bash
npm install
npm run dev
```

`vite.config.js` proxies `/api` to `http://localhost:8000`, so run the backend on
the same machine. To develop against the Pi instead, point that proxy target at
`http://herman.local` — **port 80, not 8000**. The API binds to localhost on the
Pi and is reached through nginx, so `:8000` is not open from another machine.
Going through nginx also exercises the same path the real page uses.

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
