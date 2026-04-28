type PhaseSummaryProps = {
  lines: string[];
};

export function PhaseSummary({ lines }: PhaseSummaryProps) {
  if (lines.length === 0) return null;
  return (
    <div className="phase-summary">
      {lines.map((line) => (
        <p key={line} className="phase-summary__line">{line}</p>
      ))}
    </div>
  );
}
