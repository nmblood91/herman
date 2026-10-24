import { Marked } from 'marked'
import { HELP_PAGES } from '../help/pages'
import { makeSlugger } from '../help/slug'

const CONTENTS_ID = 'help-contents'

// Every heading gets an id, so the contents box and any [text](#link) in the
// guide can jump to it. Set on the heading tokens before rendering, because a
// repeated heading's id depends on everything above it on the page.
const markdown = new Marked({
  renderer: {
    heading(token) {
      return `<h${token.depth} id="${token.id}">${this.parser.parseInline(token.tokens)}</h${token.depth}>\n`
    },
  },
})

// Built once: the guide is fixed when the app is built, so there is nothing to
// recompute per render.
const GUIDE = (() => {
  const slug = makeSlugger()
  return HELP_PAGES.map((page) => {
    const tokens = markdown.lexer(page.text)
    const headings = []
    for (const token of tokens) {
      if (token.type !== 'heading') continue
      token.id = slug(token.text)
      if (token.depth <= 3) headings.push({ id: token.id, text: token.text, depth: token.depth })
    }
    return { headings, html: markdown.parser(tokens) }
  })
})()

// The contents box, Wikipedia style: each tab, with its sections under it.
function Contents() {
  return (
    <nav className="help-contents" id={CONTENTS_ID} aria-label="Contents">
      <h2>Contents</h2>
      <ol>
        {GUIDE.map((page) => {
          const [title, ...sections] = page.headings
          if (!title) return null
          return (
            <li key={title.id}>
              <a href={`#${title.id}`}>{title.text}</a>
              {sections.length > 0 && (
                <ol>
                  {sections.map((section) => (
                    <li key={section.id}>
                      <a href={`#${section.id}`}>{section.text}</a>
                    </li>
                  ))}
                </ol>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

// One long page, opened at the top like any other tab. It used to jump to
// the section for the tab you came from, which turned out more annoying than
// helpful.
export function HelpPanel() {
  // In-page links scroll rather than change the address, so the browser's
  // back button still means "the tab before Help".
  const jump = (event) => {
    const link = event.target.closest('a[href^="#"]')
    if (!link) return
    const target = document.getElementById(link.getAttribute('href').slice(1))
    if (!target) return
    event.preventDefault()
    target.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <section className="panel-section help-page" onClick={jump}>
      <h1>Help</h1>
      <Contents />
      {GUIDE.map((entry, index) => (
        <div key={entry.headings[0]?.id ?? index} className="help-tab">
          <div dangerouslySetInnerHTML={{ __html: entry.html }} />
          <p className="help-back">
            <a href={`#${CONTENTS_ID}`}>Back to contents</a>
          </p>
        </div>
      ))}
    </section>
  )
}
