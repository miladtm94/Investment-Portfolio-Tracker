"use client";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";

const COLORS = [
  "#3b82f6", "#8b5cf6", "#10b981", "#f59e0b",
  "#ef4444", "#06b6d4", "#ec4899", "#84cc16",
];

interface Props {
  data?: Record<string, number>;
  title?: string;
}

const CustomTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-3 shadow-xl">
        <p className="text-xs text-gray-400">{payload[0].name}</p>
        <p className="text-sm font-semibold text-gray-100">{payload[0].value.toFixed(1)}%</p>
      </div>
    );
  }
  return null;
};

export function AllocationPie({ data, title = "Allocation" }: Props) {
  const chartData = Object.entries(data ?? {}).map(([name, value]) => ({ name, value }));

  return (
    <div className="card-glass p-6">
      <h3 className="text-base font-semibold text-gray-100 mb-4">{title}</h3>
      {chartData.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-gray-500 text-sm">
          No allocation data
        </div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                paddingAngle={2}
                dataKey="value"
                strokeWidth={0}
              >
                {chartData.map((_, index) => (
                  <Cell key={index} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
            </PieChart>
          </ResponsiveContainer>
          <div className="space-y-2 mt-2">
            {chartData.map((item, i) => (
              <div key={item.name} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <div
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: COLORS[i % COLORS.length] }}
                  />
                  <span className="text-gray-300">{item.name}</span>
                </div>
                <span className="font-mono text-gray-200">{item.value.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
