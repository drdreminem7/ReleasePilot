export type LabStatus = "ready" | "unavailable" | "unknown";

export function statusLabel(status: LabStatus): string {
  switch (status) {
    case "ready": return "Lab available";
    case "unavailable": return "Lab unavailable";
    case "unknown": return "Lab status unknown";
  }
}

