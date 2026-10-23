import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';

vi.mock('../features/map/FacilityMap', () => ({ FacilityMap: ({ candidates }: { candidates: { features: Array<{ properties: { selected?: boolean } }> } | null }) =>
  <div data-testid="map">selected-on-map:{candidates?.features.filter((item) => item.properties.selected).length ?? 0}</div> }));

const feature = (id: string, eligible: boolean, score: number, rank: number | null, reasons: string[] = []) => ({
  type: 'Feature' as const,
  geometry: { type: 'Point', coordinates: [77.5, 12.95] },
  properties: { candidate_id: id, candidate_type: 'collection_centre' as const,
    facility_type: 'collection_centre' as const, eligible, exclusion_reasons: reasons, score, rank },
});

describe('planner results', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      let body: Record<string, unknown>;
      if (url.includes('suitability')) body = {
        facility_type: 'collection_centre', data_status: 'synthetic_demo',
        criteria_directions: {}, weights: { demand_access: 1 }, ahp: null, assumptions: ['Synthetic fixture'],
        geojson: { type: 'FeatureCollection', features: [feature('SYN-C01', true, 88.2, 1), feature('SYN-C02', false, 62.1, null, ['hard rule'])] },
      };
      else if (url.includes('demo-inputs')) body = { data_status: 'synthetic_demo', synthetic: true, assumption: 'Synthetic estimates',
        demand_by_ward: { 'SYN-W0': 5 }, fixed_costs: { 'SYN-C01': 100 }, capacities: { 'SYN-C01': 20 },
        dismantling_fixed_costs: {}, dismantling_capacities: {} };
      else if (url.includes('facility-design/defaults')) body = { warning: 'Estimated factors', defaults: {
        daily_throughput_tonnes_per_day: 5, operating_days_per_year: 300, storage_duration_days: 7,
        plot_width_m: 80, plot_depth_m: 60, receiving_area_m2_per_tpd: .8, inspection_area_m2_per_tpd: .5,
        dismantling_area_m2_per_tpd: 3, storage_area_m2_per_stored_tonne: 2.5,
        dispatch_area_m2_per_tpd: .7, circulation_fraction: .25 } };
      else if (url.includes('facility-design/plan')) {
        const inputs = JSON.parse(String(init?.body));
        const zoneIds = ['receiving', 'inspection', 'dismantling', 'segregated_storage', 'dispatch', 'circulation'];
        body = { inputs, layout_type: 'conceptual_not_engineering_drawing', annual_throughput_tonnes: inputs.daily_throughput_tonnes_per_day * inputs.operating_days_per_year,
          storage_capacity_tonnes: inputs.daily_throughput_tonnes_per_day * inputs.storage_duration_days,
          required_area_m2: 3600, envelope_area_m2: 4800, remaining_area_m2: 1200,
          envelope: { width_m: inputs.plot_width_m, depth_m: inputs.plot_depth_m }, assumptions: ['Conceptual synthetic fixture'],
          zones: zoneIds.map((zone_id, index) => ({ zone_id, label: zone_id.replaceAll('_', ' '), x_m: index * 10, y_m: 0,
            width_m: 10, depth_m: 60, area_m2: 600 })) };
      }
      else if (url.includes('scenarios/run')) {
        const params = JSON.parse(String(init?.body));
        const score = Number(params.budget) + Number(params.capacities['SYN-C01']);
        body = { run_id: `${params.scenario_type}-id`, group_id: params.group_id, dataset_version: 'demo-v1', parameters: params,
          criteria_weights: {}, results: { scenario_type: params.scenario_type, selected_facilities: [{ candidate_id: 'SYN-C01' }],
            total_demand_tonnes: 5, allocated_tonnes: 5, unserved_tonnes: 0, service_coverage_percent: score % 100,
            total_estimated_operating_cost: score, transport_distance_km: score / 10, transport_tonne_km: score / 2, capacity_utilization_percent: 25,
            feasibility_explanation: [], candidate_scores: [
              { candidate_id: 'SYN-C01', eligible: true, suitability_score: 88, rank: 1, exclusion_reasons: [] },
              { candidate_id: 'SYN-C02', eligible: false, suitability_score: 60, rank: null, exclusion_reasons: ['hard rule'] },
            ], geojson: { type: 'FeatureCollection', features: [{ ...feature('SYN-C01', true, 88, 1), properties: { ...feature('SYN-C01', true, 88, 1).properties, selected: true, allocated_tonnes: 5 } }] } } };
      } else if (url.includes('scenarios/compare')) body = { runs: [], delta_from_first: {} };
      else body = { type: 'FeatureCollection', features: [] };
      return { ok: true, json: async () => body };
    }));
  });

  it('Reports navigation reaches an always-present section before scenarios are run', async () => {
    window.history.replaceState({}, '', '/');
    render(<App />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('link', { name: 'Reports' }));
    expect(window.location.hash).toBe('#scenario-reports');
    expect(document.getElementById('scenario-reports')).toBeInTheDocument();
    expect(screen.getByText(/Run the baseline, optimized and future scenarios above/)).toBeInTheDocument();
    window.history.replaceState({}, '', '/');
  });

  it('shows eligibility, ranking, and exclusion explanations from the API', async () => {
    render(<App />);
    expect(await screen.findByText('SYN-C01')).toBeInTheDocument();
    expect(await screen.findByText('1500.0 t/year')).toBeInTheDocument();
    expect(screen.getByText('hard rule')).toBeInTheDocument();
    expect(screen.getByText('88.2')).toBeInTheDocument();
  });

  it('re-runs suitability when the facility model changes', async () => {
    render(<App />);
    await screen.findByText('SYN-C01');
    await userEvent.selectOptions(screen.getByRole('combobox'), 'dismantling_facility');
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('suitability/evaluate'), expect.objectContaining({ body: expect.stringContaining('dismantling_facility') })));
  });

  it('recalculates annual throughput when facility design assumptions change', async () => {
    render(<App />);
    const user = userEvent.setup();
    expect(await screen.findByText('1500.0 t/year')).toBeInTheDocument();
    const throughput = screen.getByRole('spinbutton', { name: 'Daily throughput (tonnes/day)' });
    await user.clear(throughput);
    await user.type(throughput, '8');
    await user.click(screen.getByRole('button', { name: 'Calculate facility layout' }));
    expect(await screen.findByText('2400.0 t/year')).toBeInTheDocument();
    await user.clear(screen.getByRole('spinbutton', { name: 'Storage duration (days)' }));
    await user.type(screen.getByRole('spinbutton', { name: 'Storage duration (days)' }), '9');
    await user.clear(screen.getByRole('spinbutton', { name: 'Plot width (m)' }));
    await user.type(screen.getByRole('spinbutton', { name: 'Plot width (m)' }), '90');
    await user.clear(screen.getByRole('spinbutton', { name: 'Plot depth (m)' }));
    await user.type(screen.getByRole('spinbutton', { name: 'Plot depth (m)' }), '70');
    await user.click(screen.getByRole('button', { name: 'Calculate facility layout' }));
    expect(await screen.findByText('72.0 t')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /within 90 by 70 metre plot/ })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /enlarged conceptual zone detail/i })).toBeInTheDocument();
    expect(screen.getByText(/Circulation is represented as one conceptual zone/)).toBeInTheDocument();
  });

  it('sends edited budget and capacity to the API and refreshes map and scenario KPIs', async () => {
    render(<App />);
    const user = userEvent.setup();
    await screen.findByText('SYN-C01');
    await user.clear(screen.getByRole('spinbutton', { name: 'Fixed-cost budget (INR)' }));
    await user.type(screen.getByRole('spinbutton', { name: 'Fixed-cost budget (INR)' }), '700');
    await user.clear(screen.getByRole('spinbutton', { name: 'SYN-C01 capacity (tonnes/year)' }));
    await user.type(screen.getByRole('spinbutton', { name: 'SYN-C01 capacity (tonnes/year)' }), '30');
    await user.click(screen.getByRole('button', { name: /Run baseline, optimized and future scenarios/ }));
    expect(await screen.findByText('selected-on-map:1')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText('INR 730 estimated scenario cost')).toHaveLength(3));
    expect(screen.getByText(/#1 · SYN-C01 · 88.0/)).toBeInTheDocument();
    expect(screen.getByText(/Excluded · SYN-C02 · 60.0/)).toHaveTextContent('hard rule');
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('scenarios/run'), expect.objectContaining({
      body: expect.stringContaining('"budget":700'),
    }));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('scenarios/run'), expect.objectContaining({
      body: expect.stringContaining('"SYN-C01":30'),
    }));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('scenarios/run'), expect.objectContaining({
      body: expect.stringContaining('"baseline_facility_ids":["SYN-C01"]'),
    }));
  });
});
