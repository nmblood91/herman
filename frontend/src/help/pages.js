// The Help tab, in page order. Each entry is one Markdown file in this folder,
// and the tab it explains, which tests/test_help.py uses to check every tab has
// a section. To add a section, write the file and add a line here.
//
// tests/test_help.py reads this list, so keep the one-import-per-line form.
import plantsAndSoil from './plants-and-soil.md?raw'
import controls from './controls.md?raw'
import automation from './automation.md?raw'
import calibration from './calibration.md?raw'
import history from './history.md?raw'
import camera from './camera.md?raw'
import glossary from './glossary.md?raw'

export const HELP_PAGES = [
  { tab: 'plants', text: plantsAndSoil },
  { tab: 'controls', text: controls },
  { tab: 'automation', text: automation },
  { tab: 'calibration', text: calibration },
  { tab: 'history', text: history },
  { tab: 'camera', text: camera },
  { tab: null, text: glossary },
]
