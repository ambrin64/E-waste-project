import type { CityInfo, FacilityDesign, FacilityDesignInput, FacilityType, FeatureCollection, ScenarioInputs, ScenarioRun, SuitabilityResponse, WardFeatureCollection } from '../types/api';

export const API_ROOT = import.meta.env.VITE_API_ROOT ?? 'http://localhost:8000/api/v1';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const fetchLayer = (layer: string) => request<FeatureCollection>(`/datasets/${layer}/features`);
export const fetchCities = () => request<{ items: CityInfo[] }>('/cities');
export const fetchCityWards = (cityId: string) => request<WardFeatureCollection>(`/cities/${encodeURIComponent(cityId)}/wards`);

export const evaluateSuitability = (facilityType: FacilityType, constraintBufferM: number) =>
  request<SuitabilityResponse>('/suitability/evaluate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      facility_type: facilityType,
      constraint_buffer_m: constraintBufferM,
      constraint_types: ['synthetic_waterbody', 'synthetic_sensitive_use'],
      required_fields: { hard_allowed: true },
    }),
  });

export const fetchScenarioInputs = () => request<ScenarioInputs>('/scenarios/demo-inputs');

export const runScenario = (payload: Record<string, unknown>) =>
  request<ScenarioRun>('/scenarios/run', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });

export const compareScenarios = (runIds: string[]) =>
  request<{ runs: ScenarioRun[]; delta_from_first: Record<string, Record<string, number>> }>('/scenarios/compare', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_ids: runIds }),
  });

export const fetchFacilityDesignDefaults = () =>
  request<{ defaults: FacilityDesignInput; warning: string }>('/facility-design/defaults');

export const calculateFacilityDesign = (payload: FacilityDesignInput) =>
  request<FacilityDesign>('/facility-design/plan', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });

export async function downloadFacilityLayout(payload: FacilityDesignInput) {
  const response = await fetch(`${API_ROOT}/facility-design/layout.pdf`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? `Request failed (${response.status})`);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'conceptual-facility-layout.pdf'; anchor.click();
  URL.revokeObjectURL(url);
}

export const scenarioReportUrl = (runId: string, format: 'pdf' | 'csv') => `${API_ROOT}/reports/${runId}.${format}`;
