export type FacilityType = 'collection_centre' | 'dismantling_facility';

export type CandidateProperties = {
  candidate_id: string;
  candidate_type: FacilityType;
  facility_type: FacilityType;
  eligible: boolean;
  exclusion_reasons: string[];
  score: number;
  rank: number | null;
  [key: string]: unknown;
};

export type FeatureCollection = {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    geometry: { type: string; coordinates: unknown };
    properties: CandidateProperties;
  }>;
};

export type WardFeatureCollection = {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    id?: string;
    geometry: { type: string; coordinates: unknown };
    properties: Record<string, unknown>;
  }>;
};

export type CityInfo = {
  city_id: string;
  name: string;
  boundary: { source: string; source_url: string; source_year: number | null; licence: string; crs: string; feature_count: number; status: string };
  population: { source: string; source_url: string; source_year: number | null; licence: string; status: string; limitations?: string } | null;
  analysis_availability: Record<string, string>;
};

export type SuitabilityResponse = {
  facility_type: FacilityType;
  data_status: string;
  criteria_directions: Record<string, string>;
  weights: Record<string, number>;
  ahp: null | {
    weights: Record<string, number>;
    consistency_ratio: number;
    consistency_acceptable: boolean;
  };
  assumptions: string[];
  geojson: FeatureCollection;
};

export type ScenarioInputs = {
  data_status: 'synthetic_demo' | 'official' | 'estimated';
  synthetic: boolean;
  assumption: string;
  demand_by_ward: Record<string, number>;
  fixed_costs: Record<string, number>;
  capacities: Record<string, number>;
  dismantling_fixed_costs: Record<string, number>;
  dismantling_capacities: Record<string, number>;
};

export type ScenarioResults = {
  status: string;
  scenario_type: string;
  selected_facilities: Array<{ candidate_id: string; fixed_cost: number; capacity_tonnes: number; suitability_score: number }>;
  total_demand_tonnes: number;
  allocated_tonnes: number;
  unserved_tonnes: number;
  service_coverage_percent: number;
  total_estimated_operating_cost: number;
  transport_distance_km: number;
  transport_tonne_km: number;
  capacity_utilization_percent: number;
  feasibility_explanation: string[];
  candidate_scores: Array<{ candidate_id: string; eligible: boolean; suitability_score: number; rank: number | null; exclusion_reasons: string[] }>;
  geojson: FeatureCollection;
  [key: string]: unknown;
};

export type ScenarioRun = {
  run_id: string;
  group_id: string;
  dataset_version: string;
  parameters: Record<string, unknown>;
  criteria_weights: Record<string, number>;
  results: ScenarioResults;
};

export type FacilityDesignInput = {
  daily_throughput_tonnes_per_day: number;
  operating_days_per_year: number;
  storage_duration_days: number;
  plot_width_m: number;
  plot_depth_m: number;
  receiving_area_m2_per_tpd: number;
  inspection_area_m2_per_tpd: number;
  dismantling_area_m2_per_tpd: number;
  storage_area_m2_per_stored_tonne: number;
  dispatch_area_m2_per_tpd: number;
  circulation_fraction: number;
};

export type FacilityDesign = {
  layout_type: string;
  inputs: FacilityDesignInput;
  annual_throughput_tonnes: number;
  storage_capacity_tonnes: number;
  required_area_m2: number;
  process_area_m2?: number;
  circulation_area_m2?: number;
  envelope_area_m2: number;
  remaining_area_m2: number;
  envelope: { width_m: number; depth_m: number };
  zones: Array<{ zone_id: string; label: string; x_m: number; y_m: number; width_m: number; depth_m: number; area_m2: number }>;
  assumptions: string[];
};
