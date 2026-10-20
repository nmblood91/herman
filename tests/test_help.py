"""The Help tab's guide stays true to the app it describes.

The guide is Markdown in frontend/src/help, written for someone with no
technical background, so the failure that matters is a quiet one: the guide
telling a buyer to press a button that was renamed, or a link that jumps to
nothing. Nothing on screen would show either. This checks:

- every Help file is listed in pages.js, and every app tab has its section;
- every [text](#link) points at a real heading;
- every button the guide names after "press", "choose" or "hold" exists.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
HELP = SRC / "help"


def slugify(text):
    """The same rule as frontend/src/help/slug.js. Change both together."""
    return re.sub(r"[^a-z0-9 -]", "", text.lower()).strip().replace(" ", "-")


# --- every file is listed, in order, and every tab has its section ---

pages_js = (HELP / "pages.js").read_text(encoding="utf-8")
listed = re.findall(r"^import \w+ from '\./([\w-]+\.md)\?raw'", pages_js, re.M)
on_disk = sorted(path.name for path in HELP.glob("*.md"))
assert sorted(listed) == on_disk, f"pages.js lists {listed}, the folder has {on_disk}"
print(f"ok: all {len(on_disk)} Help files are listed in pages.js")

texts = {name: (HELP / name).read_text(encoding="utf-8") for name in listed}
for name, text in texts.items():
    assert text.startswith("## "), f"{name} should start with its tab's ## heading"

tab_bar = (SRC / "components" / "TabBar.jsx").read_text(encoding="utf-8")
tabs = dict(re.findall(r"\{ key: '(\w+)', label: '([^']+)' \}", tab_bar))
page_tabs = re.findall(r"\{ tab: '(\w+)', text: \w+ \}", pages_js)
for key, label in tabs.items():
    if key == "help":
        continue
    assert key in page_tabs, f"the {label} tab has no section in pages.js"
    first = texts[listed[page_tabs.index(key)]].splitlines()[0]
    assert first == f"## {label}", f"the {label} section starts {first!r}, not '## {label}'"
print(f"ok: each of the {len(tabs) - 1} tabs has a Help section under its own name")

# --- every #link points at a heading ---

seen = {}
anchors = set()
for name in listed:
    for heading in re.findall(r"^#{1,6} +(.+?) *$", texts[name], re.M):
        base = slugify(heading)
        count = seen.get(base, 0)
        seen[base] = count + 1
        anchors.add(f"{base}-{count}" if count else base)

links = [(name, target) for name in listed for target in re.findall(r"\]\(#([^)]+)\)", texts[name])]
broken = [f"{name}: #{target}" for name, target in links if target not in anchors]
assert not broken, "links to headings that do not exist:\n  " + "\n  ".join(broken)
print(f"ok: all {len(links)} links in the guide point at a heading")

# --- every named button is real ---

def ui_text():
    """The app's source with comments removed, so a button only mentioned in a
    comment does not count as existing."""
    chunks = []
    for path in (SRC / "components").glob("*.jsx"):
        if path.name == "HelpPanel.jsx":
            continue
        code = path.read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
        code = re.sub(r"(?m)^\s*//.*$", "", code)
        chunks.append(code)
    return "\n".join(chunks)


source = ui_text()
named = re.compile(r"\b(?:press|choose|hold|keep holding)\s+(?:the\s+)?\*\*([^*]+)\*\*", re.I)
missing = []
checked = 0
for name in listed:
    for label in named.findall(texts[name]):
        checked += 1
        # The whole label, as a text node or a string the code puts on screen:
        # it has to end where the label ends, or "Resume" would pass on the
        # strength of "Resume watering". A "(" or "{" may follow, so "Run
        # calibration" still finds "Run calibration ({seconds}s)".
        if not re.search(r"[>'\"`]\s*" + re.escape(label) + r"\s*[<'\"`({]", source):
            missing.append(f"{name}: {label}")
assert checked >= 10, f"only {checked} button names found; has the guide's wording changed?"
assert not missing, "the guide names buttons the app does not have:\n  " + "\n  ".join(missing)
print(f"ok: all {checked} buttons the guide tells you to press exist in the app")

print("\nall Help checks passed")
