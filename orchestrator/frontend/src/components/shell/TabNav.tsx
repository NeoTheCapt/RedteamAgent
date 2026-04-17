export type TabId = "dashboard" | "progress" | "cases" | "documents" | "events";

type TabNavProps = {
  current: TabId;
  onSelect: (tab: TabId) => void;
  counts?: Partial<Record<TabId, number | string>>;
};

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: "dashboard",  label: "Dashboard", icon: "📊" },
  { id: "progress",   label: "Progress",  icon: "🎯" },
  { id: "cases",      label: "Cases",     icon: "📋" },
  { id: "documents",  label: "Documents", icon: "📄" },
  { id: "events",     label: "Events",    icon: "📡" },
];

export function TabNav({ current, onSelect, counts = {} }: TabNavProps) {
  return (
    <div className="tab-nav" role="tablist">
      {TABS.map((t) => {
        const count = counts[t.id];
        const selected = current === t.id;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={selected}
            className={`tab-nav__item ${selected ? "tab-nav__item--on" : ""}`}
            onClick={() => onSelect(t.id)}
            type="button"
          >
            <span aria-hidden>{t.icon}</span>
            <span>{t.label}</span>
            {count !== undefined && <span className="tab-nav__count">{count}</span>}
          </button>
        );
      })}
    </div>
  );
}
