import { usePageTabsStore } from "../../stores/pageTabs";

export function PageTabs() {
  const pages = usePageTabsStore(s => s.pages);
  const activeTabId = usePageTabsStore(s => s.activeTabId);
  const setActive = usePageTabsStore(s => s.setActiveTab);
  const orphanCount = usePageTabsStore(s => s.orphanCount);

  // Render the nav if any page exists OR there are orphan tasks to expose.
  if (pages.length === 0 && orphanCount === 0) return null;

  return (
    <nav className="page-tabs" role="tablist">
      {pages.map(p => (
        <button
          key={p.id}
          role="tab"
          aria-selected={activeTabId === p.id}
          className={activeTabId === p.id ? "tab active" : "tab"}
          onClick={() => setActive(p.id)}
        >
          <span className={`tab-source-dot ${p.source}`} />
          <span className="tab-name">{p.name}</span>
        </button>
      ))}
      {orphanCount > 0 && (
        <button
          role="tab"
          aria-selected={activeTabId === "orphan"}
          className={activeTabId === "orphan" ? "tab active orphan" : "tab orphan"}
          onClick={() => setActive("orphan")}
        >
          <span className="tab-name">已停用</span>
          <span className="tab-count">{orphanCount}</span>
        </button>
      )}
    </nav>
  );
}
