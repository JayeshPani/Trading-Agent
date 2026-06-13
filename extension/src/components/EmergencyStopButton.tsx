import { AlertTriangle } from "lucide-react";

type EmergencyStopButtonProps = {
  disabled?: boolean;
  onClick: () => void;
};

export function EmergencyStopButton({ disabled, onClick }: EmergencyStopButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="inline-flex h-10 items-center gap-2 rounded-md bg-danger px-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
      title="Emergency stop"
    >
      <AlertTriangle size={18} aria-hidden="true" />
      Stop
    </button>
  );
}
