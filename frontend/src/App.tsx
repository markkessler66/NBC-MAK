import { useState } from "react";
import { api } from "./api";
import { usePoll } from "./hooks";
import { deg } from "./lib/format";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Dashboard } from "./pages/Dashboard";
import { Tropical } from "./pages/Tropical";
import { Verification } from "./pages/Verification";
import { Status } from "./pages/Status";

const TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "tropical", label: "Tropical" },
  { id: "verification", label: "Verification" },
  { id: "status", label: "System" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function App() {
  const [tab, setTab] = useState<TabId>("dashboard");
  const current = usePoll(api.current, 60 * 1000);
  const alerts = usePoll(api.alerts, 2 * 60 * 1000);
  const meta = usePoll(api.meta, 60 * 60 * 1000);

  const alertCount = alerts.data?.alerts.length ?? 0;
  const obs = current.data?.observation;

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur sticky top-0 z-20">
        <div className="max-w-[1500px] mx-auto px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-2">
          <div>
            <h1 className="text-sm font-bold tracking-[0.2em] text-slate-100 uppercase">
              Personal Weather Lab
            </h1>
            <div className="text-[11px] text-slate-500">
              {meta.data?.location.name ?? "…"} · Phase {meta.data?.phase ?? 1} · local forecasting laboratory
            </div>
          </div>

          <nav className="flex gap-1 order-3 md:order-2 w-full md:w-auto">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  tab === t.id
                    ? "bg-sky-600/90 text-white"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3 order-2 md:order-3">
            {alertCount > 0 && (
              <span className="text-[11px] px-2 py-1 rounded-full bg-rose-500/15 text-rose-300 border border-rose-500/30 font-semibold">
                {alertCount} alert{alertCount > 1 ? "s" : ""}
              </span>
            )}
            {obs && (
              <div className="text-right">
                <span className="text-xl font-light font-mono text-slate-100">{deg(obs.temp_f)}</span>
                <span className="text-[11px] text-slate-500 ml-2">{obs.description}</span>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-[1500px] mx-auto px-4 py-4">
        <ErrorBoundary key={tab} label={TABS.find((t) => t.id === tab)?.label ?? tab}>
          {tab === "dashboard" && <Dashboard current={current.data} alerts={alerts.data?.alerts ?? []} />}
          {tab === "tropical" && <Tropical />}
          {tab === "verification" && <Verification />}
          {tab === "status" && <Status />}
        </ErrorBoundary>
      </main>

      <footer className="max-w-[1500px] mx-auto px-4 pb-6 text-[11px] text-slate-600">
        Data: NWS/NOAA · Open-Meteo (HRRR, GFS, ECMWF IFS/AIFS, NBM, GEFS) · NHC · Iowa Environmental
        Mesonet NEXRAD. Forecasts show explicit model disagreement by design — never trust a single number.
      </footer>
    </div>
  );
}
