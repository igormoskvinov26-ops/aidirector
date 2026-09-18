import { useId } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useDark, палитраГрафика } from "./тема";

export interface MetricPoint {
  date: string;
  value: number;
}

export type ТонГрафика = "profit" | "loss" | "accent";

interface MetricChartProps {
  points: MetricPoint[];
  label: string;
  тон?: ТонГрафика;
  /** Добавляется к числу в подсказке: "%" для процентных показателей. */
  suffix?: string;
  height?: number;
}

/** Один линейный график для «клика на плитку» — решение владельца
 *  18.09.2026: у каждого показателя должна быть видна динамика по дням, не
 *  только текущее значение. Общий для «Клиентской базы» (где он подменяет
 *  собой «Пульс базы») и «Записей за месяц» (где такого блока раньше не
 *  было вовсе).
 *
 *  Цвет — по смыслу показателя, не подряд: «profit» для положительных
 *  (повторные, активная база), «loss» для отрицательных (потерянные),
 *  «accent» — нейтральный (возвращаемость, уникальные клиенты). */
export function MetricChart({ points, label, тон = "accent", suffix = "", height = 260 }: MetricChartProps) {
  const тёмная = useDark();
  const цвета = палитраГрафика(тёмная);
  const цвет = тон === "profit" ? цвета.прибыль : тон === "loss" ? цвета.убыток : цвета.золото;
  const gradientId = `metric-fill-${useId().replace(/[:]/g, "")}`;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={points} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={цвет} stopOpacity={0.28} />
            <stop offset="100%" stopColor={цвет} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={цвета.сетка} vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 11, fill: цвета.ось }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(d: string) => d.slice(5)}
          minTickGap={24}
        />
        <YAxis tick={{ fontSize: 11, fill: цвета.ось }} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={{
            background: цвета.подсказкаФон,
            border: `1px solid ${цвета.подсказкаРамка}`,
            borderRadius: "12px",
            fontSize: 12,
          }}
          formatter={(value) => [`${value ?? ""}${suffix}`, label]}
        />
        <Area
          type="monotone"
          dataKey="value"
          name={label}
          stroke={цвет}
          strokeWidth={2.5}
          fill={`url(#${gradientId})`}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
