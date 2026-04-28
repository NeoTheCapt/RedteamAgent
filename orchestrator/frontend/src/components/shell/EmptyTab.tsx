type EmptyTabProps = {
  label: string;
  note?: string;
};

export function EmptyTab({ label, note }: EmptyTabProps) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", height: "60vh", color: "var(--c-text-dim)",
      gap: "var(--sp-3)", fontFamily: "var(--font-mono)",
    }}>
      <div style={{ fontSize: "var(--fs-xl)", color: "var(--c-text-muted)" }}>
        {label}
      </div>
      <div style={{ fontSize: "var(--fs-sm)" }}>
        {note ?? "Coming in a later plan."}
      </div>
    </div>
  );
}
