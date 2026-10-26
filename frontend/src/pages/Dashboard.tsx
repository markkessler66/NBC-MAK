import { api } from "../api";
import { usePoll } from "../hooks";
import type { CurrentPayload, AlertData } from "../types";
import { CurrentConditions } from "../components/CurrentConditions";
import { AlertsPanel } from "../components/AlertsPanel";
import { ForecastChart } from "../components/ForecastChart";
import { ComparisonPanel } from "../components/ComparisonPanel";
import { DailyStrip } from "../components/DailyStrip";
import { RadarMap } from "../components/RadarMap";

interface Props {
  current: CurrentPayload | null;
  alerts: AlertData[];
}

export function Dashboard({ current, alerts }: Props) {
  const forecast = usePoll(api.forecast, 5 * 60 * 1000);

  return (
    <div className="space-y-4">
      <div className="grid lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3">
          <CurrentConditions obs={current?.observation ?? null} />
        </div>
        <div className="lg:col-span-2">
          <AlertsPanel alerts={alerts} />
        </div>
      </div>

      {forecast.error && !forecast.data && (
        <div className="card p-4 text-sm text-amber-300">
          Forecast engine warming up: {forecast.error}
        </div>
      )}

      {forecast.data && (
        <>
          <DailyStrip daily={forecast.data.daily} />
          <ForecastChart payload={forecast.data} />
          <div className="grid lg:grid-cols-2 gap-4">
            <ComparisonPanel payload={forecast.data} />
            <RadarMap
              lat={forecast.data.location.lat}
              lon={forecast.data.location.lon}
              label={forecast.data.location.name}
            />
          </div>
        </>
      )}
    </div>
  );
}
