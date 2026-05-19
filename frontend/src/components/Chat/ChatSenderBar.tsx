import { useEffect, useRef, useState } from "react";
import { patchWatchedSenders } from "../../api/chat";
import type { SenderMode } from "./ChatBoardPanel";

interface Author { name: string; count: number; }

interface Props {
  pageId: string;
  authors: Author[];
  watchedSenders: string[];
  onChange: (next: string[]) => void;
  mode: SenderMode;
  onModeChange: (next: SenderMode) => void;
  /** Optional map from sender name → signal-source type. When present, the
   *  chip renders a small colored dot prefix so monitor senders are
   *  visually distinct from human chat senders. Defaults to `{}` so
   *  existing callers that don't pass it continue to work without changes. */
  monitorSources?: Record<string, "stock" | "option">;
}

function FilterGlyph() {
  return (
    <svg viewBox="0 0 14 14" width="12" height="12" fill="none"
         stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
         aria-hidden="true">
      <path d="M2 3 h10 l-3.5 4.5 v3.5 l-3 -1.5 v-2 z" />
    </svg>
  );
}

function HighlightGlyph() {
  return (
    <svg viewBox="0 0 14 14" width="12" height="12" fill="none"
         stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
         aria-hidden="true">
      <path d="M1.5 7 C 3 4 5 2.5 7 2.5 C 9 2.5 11 4 12.5 7 C 11 10 9 11.5 7 11.5 C 5 11.5 3 10 1.5 7 Z" />
      <circle cx="7" cy="7" r="1.8" fill="currentColor" stroke="none" />
    </svg>
  );
}

/**
 * Watched-sender editor for chat pages. Inspired by ``PageWhitelistBar``:
 *
 * - Default: only the currently watched senders render as chips; hover
 *   flips the chip to a delete affordance.
 * - "修改发送者" opens a popover listing every author seen this week
 *   (with msg counts). Clicking one adds it to the watched list and
 *   auto-closes the popover. Already-watched names are hidden from the
 *   popover — there's nothing to "add" for them.
 *
 * Persists via PATCH /api/whop/pages/{id}/settings ``watched_senders``.
 */
export function ChatSenderBar({
  pageId, authors, watchedSenders, onChange, mode, onModeChange,
  monitorSources = {},
}: Props) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  // Close when the user clicks outside the popover. The trigger button
  // is excluded too — otherwise clicking the "发送者" label while open
  // would race the document handler (close → onClick toggle → reopen)
  // and net out as "stays open". Excluding it lets the trigger's own
  // onClick handle the toggle cleanly. Watched chips, mode glyph,
  // anywhere else in the page → close. Esc also closes.
  useEffect(() => {
    if (!popoverOpen) return;
    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (popoverRef.current?.contains(target)) return;
      if (triggerRef.current?.contains(target)) return;
      setPopoverOpen(false);
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPopoverOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [popoverOpen]);

  const watched = new Set(watchedSenders);

  async function persist(next: string[]) {
    onChange(next);
    try { await patchWatchedSenders(pageId, next); } catch { /* surfaced via store later */ }
  }

  function handleRemove(name: string) {
    void persist(watchedSenders.filter((s) => s !== name));
  }

  function handleAdd(name: string) {
    if (watched.has(name)) return;
    void persist([...watchedSenders, name]);
    setPopoverOpen(false);
  }

  // Authors not yet watched, ordered by msg count desc (most active first
  // — matches the order shown in the old all-authors strip).
  const addable = authors.filter((a) => !watched.has(a.name));

  return (
    <div className="chat-sender-bar">
      <div className="chat-sender-label-wrap">
        <button
          ref={triggerRef}
          type="button"
          className="chat-sender-label"
          onClick={() => setPopoverOpen((v) => !v)}
          aria-haspopup="listbox"
          aria-expanded={popoverOpen}
          title={mode === "filter" ? "过滤模式（仅显示已关注）" : "关注模式（全部显示，已关注高亮）"}
        >
          <span className="chat-sender-mode-glyph">
            {mode === "filter" ? <FilterGlyph /> : <HighlightGlyph />}
          </span>
          发送者
        </button>
        {popoverOpen && (
          <div className="chat-sender-popover" role="listbox" ref={popoverRef}>
            <div className="chat-sender-mode-switch" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={mode === "filter"}
                className={`chat-sender-mode-btn${mode === "filter" ? " active" : ""}`}
                onClick={() => onModeChange("filter")}
              >
                <FilterGlyph />
                过滤
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "highlight"}
                className={`chat-sender-mode-btn${mode === "highlight" ? " active" : ""}`}
                onClick={() => onModeChange("highlight")}
              >
                <HighlightGlyph />
                关注
              </button>
            </div>
            {addable.length === 0 ? (
              <div className="chat-sender-popover-empty">
                {authors.length === 0 ? "本周尚无发送者" : "全部已添加"}
              </div>
            ) : (
              <div className="chat-sender-popover-grid">
                {addable.map((a) => {
                  const popoverSource = monitorSources[a.name];
                  return (
                    <button
                      key={a.name}
                      type="button"
                      className={`chat-sender-popover-item${popoverSource ? " monitor" : ""}`}
                      onClick={() => handleAdd(a.name)}
                      role="option"
                      aria-selected={false}
                      title={`${a.name} · ${a.count} 条`}
                    >
                      {popoverSource && (
                        <span className={`src-dot ${popoverSource}`} aria-hidden="true" />
                      )}
                      <span className="chat-sender-popover-avatar">{a.name.slice(-1)}</span>
                      <span className="chat-sender-popover-name">{a.name}</span>
                      <span className="chat-sender-popover-count">{a.count}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {watchedSenders.length === 0 && (
        <span className="chat-sender-empty">未配置 — 点"发送者"添加</span>
      )}

      {watchedSenders.map((name) => {
        const chipSource = monitorSources[name];
        return (
          <button
            key={name}
            type="button"
            className={`chat-watched-chip${chipSource ? " monitor" : ""}`}
            onClick={() => handleRemove(name)}
            aria-label={`删除 ${name}`}
            title={`点击删除 ${name}`}
          >
            {chipSource && (
              <span className={`src-dot ${chipSource}`} aria-hidden="true" />
            )}
            <span className="chat-watched-chip-avatar">{name.slice(-1)}</span>
            <span className="chat-watched-chip-name">{name}</span>
            <span className="chat-watched-chip-del" aria-hidden="true">
              <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <line x1="3" y1="3" x2="9" y2="9" />
                <line x1="9" y1="3" x2="3" y2="9" />
              </svg>
            </span>
          </button>
        );
      })}
    </div>
  );
}
