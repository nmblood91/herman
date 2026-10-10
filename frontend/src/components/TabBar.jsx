export function TabBar({ activeTab, onChange }) {
  // Ordered by how often you open them: what the plants are doing, then
  // driving the thing by hand, then what it does unattended, then the
  // build-time facts and checks, then the trend you consult afterwards.
  //
  // There is no Settings tab. It had become the place where unrelated things
  // landed -- "does this water by itself" sat next to "which LED strip did you
  // solder on" -- and each of its groups belongs with the thing it governs.
  const tabs = [
    { key: 'plants', label: 'Plants and Soil' },
    { key: 'controls', label: 'Controls' },
    { key: 'automation', label: 'Automation' },
    { key: 'calibration', label: 'Calibration' },
    { key: 'history', label: 'History' },
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
