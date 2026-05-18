import { useEffect, useState } from "react";
import { api, HttpError, type DbRowsResponse } from "../../api/http";

const PAGE_SIZE = 15;
const JSON_TRUNCATE = 80;

interface Props {
  table: string;
}

function renderCell(value: unknown): { text: string; title?: string } {
  if (value === null || value === undefined) {
    return { text: "—" };
  }
  if (typeof value === "object") {
    const full = JSON.stringify(value);
    const text = full.length > JSON_TRUNCATE ? full.slice(0, JSON_TRUNCATE) + "…" : full;
    return { text, title: full };
  }
  return { text: String(value) };
}

export function GenericDbTable({ table }: Props) {
  const [data, setData] = useState<DbRowsResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setOffset(0);
  }, [table]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listDbRows(table, { limit: PAGE_SIZE, offset })
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof HttpError) setError(e.message);
        else setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [table, offset]);

  const total = data?.total ?? 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <>
      {error && <div className="db-error">{error}</div>}

      {!loading && data && data.rows.length === 0 ? (
        <div className="empty-state">
          <p>表 <code>{table}</code> 暂无数据。</p>
        </div>
      ) : (
        <div className="db-table-wrap">
          <table className="db-table">
            <thead>
              <tr>
                {data?.columns.map((col) => (
                  <th key={col}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => {
                    const rendered = renderCell(cell);
                    return (
                      <td key={j} title={rendered.title}>
                        {rendered.text}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <footer className="db-pagination">
        <button
          className="db-page-btn"
          onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
          disabled={loading || !hasPrev}
        >
          上一页
        </button>
        <span className="db-page-indicator">
          第 {currentPage} 页 / 共 {totalPages} 页
        </span>
        <button
          className="db-page-btn"
          onClick={() => setOffset((o) => o + PAGE_SIZE)}
          disabled={loading || !hasNext}
        >
          下一页
        </button>
      </footer>
    </>
  );
}
