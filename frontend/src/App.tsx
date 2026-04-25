export default function App() {
  return (
    <div style={{
      padding: "var(--space-4)",
      minHeight: "100vh",
      background: "var(--bg-0)",
      color: "var(--fg-1)",
    }}>
      <h1 style={{ fontSize: 18, fontWeight: 600, margin: 0, marginBottom: "var(--space-4)" }}>
        Signal Station
      </h1>
      <p style={{ color: "var(--fg-2)", fontSize: 13 }}>
        Design system loaded. Tokens + fonts OK.
      </p>
      <div style={{
        marginTop: "var(--space-4)",
        display: "flex",
        gap: "var(--space-2)",
        flexWrap: "wrap",
      }}>
        {[
          { name: "bg-1", val: "var(--bg-1)" },
          { name: "bg-2", val: "var(--bg-2)" },
          { name: "brand", val: "var(--brand)" },
          { name: "ok", val: "var(--ok)" },
          { name: "err", val: "var(--err)" },
          { name: "warn", val: "var(--warn)" },
          { name: "info", val: "var(--info)" },
          { name: "type-stock", val: "var(--type-stock-fg)" },
          { name: "type-option", val: "var(--type-option-fg)" },
        ].map(({ name, val }) => (
          <div key={name} style={{
            padding: "var(--space-2) var(--space-3)",
            borderRadius: "var(--radius-chip)",
            background: "var(--bg-1)",
            border: "1px solid var(--line)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: val,
          }}>
            {name}
          </div>
        ))}
      </div>
    </div>
  );
}
