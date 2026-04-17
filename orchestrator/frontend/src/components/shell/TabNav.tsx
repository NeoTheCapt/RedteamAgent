import { type KeyboardEvent, useRef } from "react";

export type TabId = "dashboard" | "progress" | "cases" | "documents" | "events";

const TABS: { id: TabId; label: string }[] = [
  { id: "dashboard",  label: "Dashboard" },
  { id: "progress",   label: "Progress"  },
  { id: "cases",      label: "Cases"     },
  { id: "documents",  label: "Documents" },
  { id: "events",     label: "Events"    },
];

type TabNavProps = {
  current: TabId;
  onSelect: (tab: TabId) => void;
  counts?: Partial<Record<TabId, number | string>>;
};

export function TabNav({ current, onSelect, counts = {} }: TabNavProps) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const order = TABS.map((t) => t.id);
    const idx = order.indexOf(current);
    if (idx < 0) return;
    let next: TabId | null = null;
    if (e.key === "ArrowRight") next = order[(idx + 1) % order.length];
    else if (e.key === "ArrowLeft") next = order[(idx - 1 + order.length) % order.length];
    else if (e.key === "Home") next = order[0];
    else if (e.key === "End") next = order[order.length - 1];
    if (next) {
      e.preventDefault();
      onSelect(next);
      requestAnimationFrame(() => refs.current[next!]?.focus());
    }
  }

  return (
    <div className="tab-nav" role="tablist" onKeyDown={onKeyDown}>
      {TABS.map((t) => {
        const count = counts[t.id];
        const selected = current === t.id;
        return (
          <button
            key={t.id}
            ref={(el) => { refs.current[t.id] = el; }}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={selected}
            aria-controls={`tabpanel-${t.id}`}
            tabIndex={selected ? 0 : -1}
            className={`tab-nav__item ${selected ? "tab-nav__item--on" : ""}`}
            onClick={() => onSelect(t.id)}
            type="button"
          >
            <span>{t.label}</span>
            {count !== undefined && <span className="tab-nav__count">{count}</span>}
          </button>
        );
      })}
    </div>
  );
}
