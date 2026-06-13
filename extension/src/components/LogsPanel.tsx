import { LiveStatus } from "../api/client";

type LogsPanelProps = {
  logs: LiveStatus["logs"];
};

export function LogsPanel({ logs }: LogsPanelProps) {
  return (
    <section className="rounded-md border border-stone-200 bg-white">
      <div className="border-b border-stone-200 px-4 py-3">
        <h2 className="text-base font-semibold text-ink">Logs</h2>
      </div>
      <div className="max-h-56 overflow-auto p-3">
        {logs.length === 0 ? (
          <div className="text-sm text-stone-500">No logs yet</div>
        ) : (
          <div className="space-y-2">
            {logs
              .slice()
              .reverse()
              .map((log, index) => (
                <div key={`${log.created_at}-${index}`} className="rounded-md bg-panel px-3 py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className={log.level === "WARNING" || log.level === "ERROR" ? "font-semibold text-warning" : "font-semibold text-stone-700"}>
                      {log.level}
                    </span>
                    <span className="text-xs text-stone-500">{new Date(log.created_at).toLocaleTimeString()}</span>
                  </div>
                  <div className="mt-1 text-stone-700">{log.message}</div>
                </div>
              ))}
          </div>
        )}
      </div>
    </section>
  );
}
