import "../Card/Card.css";

export interface TypeBadgeProps {
  type: "stock" | "option";
}

export function TypeBadge({ type }: TypeBadgeProps) {
  return (
    <span className={`type-badge ${type}`}>
      {type === "stock" ? "正股" : "期权"}
    </span>
  );
}
