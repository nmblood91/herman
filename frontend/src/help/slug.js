// A heading's link name: lower case, punctuation dropped, spaces as dashes, the
// way GitHub and VS Code's preview name them, so a link written while
// previewing a file in VS Code works the same here. "Limit / home switch"
// becomes limit--home-switch, and "Gantry (arm)" becomes gantry-arm.
//
// tests/test_help.py has the same rule, to check every #link in the guide
// points at a real heading. Change both together.
export const slugify = (text) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9 -]/g, '')
    .trim()
    .replace(/ /g, '-')

// A second heading with the same name gets -1, the third -2, and so on, in
// page order. "If something looks wrong" ends every tab's section this way.
export const makeSlugger = () => {
  const seen = new Map()
  return (text) => {
    const base = slugify(text)
    const count = seen.get(base) ?? 0
    seen.set(base, count + 1)
    return count ? `${base}-${count}` : base
  }
}
