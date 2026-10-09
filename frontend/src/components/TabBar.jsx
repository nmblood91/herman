export function TabBar({ activeTab, onChange }) {
  // Plants first: it is the screen someone opens to see how their plants are.
  // Controls held that slot only because it was built first.
  const tabs = [
    { key: 'plants', label: 'Plants' },
    { key: 'controls', label: 'Controls' },
    { key: 'diagnostics', label: 'Diagnostics' },
    { key: 'settings', label: 'Settings' },
  ]

  return (
    <nav className="tab-bar">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          className={activeTab === tab.key ? 'tab active' : 'tab'}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  )
}
