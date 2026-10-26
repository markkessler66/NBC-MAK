import { useEffect, useRef } from "react";
import * as echarts from "echarts";

/** Mount an ECharts instance on a div and keep it synced with `option`. */
export function useECharts(option: echarts.EChartsCoreOption | null) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (chartRef.current && option) {
      // Merge-update with series replacement: diffs in place instead of
      // clearing the canvas, so data refreshes don't flash the whole chart.
      chartRef.current.setOption(option, { replaceMerge: ["series"] });
    }
  }, [option]);

  return ref;
}
