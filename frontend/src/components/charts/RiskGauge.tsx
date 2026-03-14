"use client";

export function RiskGauge({ value, label }: { value: number; label: string }) {
  // Simple placeholder component
  const clampedValue = Math.max(0, Math.min(100, value));
  const color = clampedValue < 33 ? "#10b981" : clampedValue < 66 ? "#f59e0b" : "#ef4444";

  return (
    <div className="card-glass p-4 text-center">
      <div className="text-4xl font-bold" style={{ color }}>
        {clampedValue.toFixed(0)}
      </div>
      <div className="text-xs text-gray-400 mt-1">{label}</div>
    </div>
  );
}
