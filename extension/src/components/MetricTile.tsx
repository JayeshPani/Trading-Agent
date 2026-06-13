type MetricTileProps = {
  label: string;
  value: string;
  tone?: "default" | "danger" | "warning";
};

export function MetricTile({ label, value, tone = "default" }: MetricTileProps) {
  const toneClass =
    tone === "danger" ? "text-danger" : tone === "warning" ? "text-warning" : "text-ink";
  return (
    <div className="rounded-md border border-stone-200 bg-white p-3">
      <div className="text-xs font-medium uppercase tracking-normal text-stone-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
