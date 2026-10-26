import { useMemo } from "react";
import type { EnvironmentPoint } from "../../types";
import { useECharts } from "../useECharts";

const SST_FLOOR_C = 26.5;
const SHEAR_LIMIT_KT = 20;

const COLORS = {
  wind: "#f8fafc",
  shear: "#f472b6",
  sst: "#fb923c",
  rh: "#38bdf8",
};

/** NHC's intensity forecast against the environment it has to survive.
 *
 *  Plotting them on one time axis is the point: it shows whether the official
 *  forecast is being driven by the ingredients or in spite of them.
 */
export function EnvironmentChart({ points }: { points: EnvironmentPoint[] }) {
  const option = useMemo(() => {
    const hours = points.map((p) => p.fcst_hour);
    const pick = <T,>(fn: (p: EnvironmentPoint) => T) => points.map(fn);

    return {
      backgroundColor: "transparent",
      animation: false,
      grid: { left: 44, right: 52, top: 34, bottom: 46 },
      legend: {
        top: 0,
        textStyle: { color: "#94a3b8", fontSize: 11 },
        inactiveColor: "#334155",
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#0f172acc",
        borderColor: "#334155",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
        axisPointer: { lineStyle: { color: "#475569" } },
      },
      xAxis: {
        type: "category",
        data: hours.map((h) => (h === 0 ? "Now" : `${h}h`)),
        axisLine: { lineStyle: { color: "#334155" } },
        axisLabel: { color: "#64748b", fontSize: 11 },
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: "value",
          name: "kt / %",
          nameTextStyle: { color: "#64748b", fontSize: 10 },
          min: 0,
          axisLabel: { color: "#64748b", fontSize: 11 },
          splitLine: { lineStyle: { color: "#1e293b" } },
        },
        {
          type: "value",
          name: "°C",
          nameTextStyle: { color: "#64748b", fontSize: 10 },
          scale: true,
          axisLabel: { color: "#64748b", fontSize: 11 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "NHC intensity",
          type: "line",
          yAxisIndex: 0,
          data: pick((p) => p.nhc_wind_kt),
          lineStyle: { width: 2.8, color: COLORS.wind },
          itemStyle: { color: COLORS.wind },
          symbolSize: 6,
          z: 10,
          tooltip: { valueFormatter: (v: unknown) => (v == null ? "—" : `${v} kt`) },
        },
        {
          name: "Deep-layer shear",
          type: "line",
          yAxisIndex: 0,
          data: pick((p) => p.shear?.magnitude_kt ?? null),
          lineStyle: { width: 1.8, color: COLORS.shear },
          itemStyle: { color: COLORS.shear },
          symbolSize: 5,
          tooltip: { valueFormatter: (v: unknown) => (v == null ? "—" : `${v} kt`) },
          markLine: {
            silent: true,
            symbol: "none",
            label: {
              formatter: `${SHEAR_LIMIT_KT} kt — shear turns hostile`,
              color: "#f472b6",
              fontSize: 10,
              position: "insideEndTop",
            },
            lineStyle: { color: "#f472b6", type: "dashed", opacity: 0.5 },
            data: [{ yAxis: SHEAR_LIMIT_KT }],
          },
        },
        {
          name: "Mid-level RH",
          type: "line",
          yAxisIndex: 0,
          data: pick((p) => p.rh_700_pct),
          lineStyle: { width: 1.2, color: COLORS.rh, type: "dotted" },
          itemStyle: { color: COLORS.rh },
          symbolSize: 4,
          tooltip: { valueFormatter: (v: unknown) => (v == null ? "—" : `${v}%`) },
        },
        {
          name: "SST",
          type: "line",
          yAxisIndex: 1,
          data: pick((p) => p.sst_c),
          connectNulls: false,
          lineStyle: { width: 2, color: COLORS.sst },
          itemStyle: { color: COLORS.sst },
          symbolSize: 5,
          tooltip: { valueFormatter: (v: unknown) => (v == null ? "over land" : `${v} °C`) },
          markLine: {
            silent: true,
            symbol: "none",
            label: {
              formatter: `${SST_FLOOR_C} °C floor`,
              color: "#fb923c",
              fontSize: 10,
              position: "insideStartTop",
            },
            lineStyle: { color: "#fb923c", type: "dashed", opacity: 0.55 },
            data: [{ yAxis: SST_FLOOR_C }],
          },
        },
      ],
    };
  }, [points]);

  const chartRef = useECharts(option);
  return <div ref={chartRef} className="h-72 w-full" />;
}
