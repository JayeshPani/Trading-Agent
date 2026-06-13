type ModeBadgeProps = {
  mode: "paper" | "live";
};

export function ModeBadge({ mode }: ModeBadgeProps) {
  const live = mode === "live";
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-1 text-xs font-semibold ${
        live ? "bg-danger text-white" : "bg-emerald-100 text-emerald-800"
      }`}
    >
      {live ? "LIVE" : "PAPER"}
    </span>
  );
}
