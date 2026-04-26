import "../Card/Card.css";

export interface StatusPillProps {
  status: string;
}

function statusClass(status: string): string {
  switch (status) {
    case "FILLED":
      return "status-filled";
    case "PARTIAL":
      return "status-partial";
    case "PENDING":
    case "SUBMITTED":
    case "NEW":
    case "MODIFIED":
    case "PARSING":
    case "INSTRUCTION_READY":
    case "SUBMITTING":
    case "RECEIVED":
      return "status-pending";
    case "CANCELLED":
    case "SKIPPED":
      return "status-cancelled";
    case "REJECTED":
      return "status-rejected";
    case "PARSE_ERROR":
    case "SUBMIT_FAILED":
      return "status-error";
    default:
      return "status-cancelled";
  }
}

function statusLabel(status: string): string {
  // Abbreviate long labels for compact display
  if (status === "PARSE_ERROR") return "PARSE_ERR";
  if (status === "SUBMIT_FAILED") return "SUBMIT_FAIL";
  if (status === "INSTRUCTION_READY") return "INSTR_READY";
  return status;
}

export function StatusPill({ status }: StatusPillProps) {
  const cls = statusClass(status);
  return (
    <span className={`card-status ${cls}`}>
      {statusLabel(status)}
    </span>
  );
}
