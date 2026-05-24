import type { TabDef } from "./DetailTabSwipe";

interface Props {
  tabs: TabDef[];
  index: number;
  onIndexChange: (i: number) => void;
  onOpenSettings?: (i: number) => void;
}

export function DetailTabFooter({ tabs, index, onIndexChange, onOpenSettings }: Props) {
  const active = tabs[index]!;
  return (
    <div className="detail-tab-footer">
      <button
        type="button"
        className="detail-tab-footer-settings"
        onClick={() => onOpenSettings?.(index)}
        aria-label={`${active.label} 设置`}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
        <span>{active.label}</span>
      </button>
      <div className="detail-tab-indicator">
        {tabs.map((t, i) => (
          <button
            type="button"
            key={t.id}
            className={`detail-tab-dot ${i === index ? "active" : ""}`}
            onClick={() => onIndexChange(i)}
            aria-label={`切换到 ${t.label}`}
          />
        ))}
      </div>
    </div>
  );
}
