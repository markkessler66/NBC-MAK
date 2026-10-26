import type {
  CurrentPayload,
  AlertData,
  ForecastPayload,
  TropicalPayload,
  StormDetailPayload,
  StormFieldsPayload,
  ScenarioAdjustments,
  ScenarioPayload,
  VerificationPayload,
  StatusPayload,
  MetaPayload,
} from "./types";

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return resp.json();
}

export const api = {
  meta: () => getJson<MetaPayload>("/api/meta"),
  current: () => getJson<CurrentPayload>("/api/current"),
  alerts: () => getJson<{ alerts: AlertData[] }>("/api/alerts"),
  forecast: () => getJson<ForecastPayload>("/api/forecast"),
  tropical: () => getJson<TropicalPayload>("/api/tropical"),
  tropicalStorm: (id: string) =>
    getJson<StormDetailPayload>(`/api/tropical/${encodeURIComponent(id)}`),
  tropicalFields: (id: string, hour: number) =>
    getJson<StormFieldsPayload>(
      `/api/tropical/${encodeURIComponent(id)}/fields?hour=${hour}`,
    ),
  tropicalScenario: (id: string, adjustments: ScenarioAdjustments) =>
    getJson<ScenarioPayload>(
      `/api/tropical/${encodeURIComponent(id)}/scenario?` +
        new URLSearchParams(
          Object.entries(adjustments).map(([k, v]) => [k, String(v)]),
        ).toString(),
    ),
  verification: (variable: string, days: number) =>
    getJson<VerificationPayload>(`/api/verification?var=${variable}&days=${days}`),
  status: () => getJson<StatusPayload>("/api/status"),
};
