import { useEffect, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { compareScenarios, evaluateSuitability, fetchCities, fetchCityWards, fetchLayer, fetchScenarioInputs, runScenario, scenarioReportUrl } from '../lib/api';
import { FacilityMap } from '../features/map/FacilityMap';
import { FacilityDesigner } from '../features/facility/FacilityDesigner';
import type { CityInfo, FacilityType, FeatureCollection, ScenarioInputs, ScenarioRun, SuitabilityResponse, WardFeatureCollection } from '../types/api';

type Layers = { wards: WardFeatureCollection | null; roads: FeatureCollection | null; constraints: FeatureCollection | null };

const scrollToSection = (id: string) => (event: ReactMouseEvent<HTMLAnchorElement>) => {
  event.preventDefault();
  const section = document.getElementById(id);
  if (!section) return;
  window.history.pushState(null, '', `#${id}`);
  section.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

export default function App() {
  const [cityId, setCityId] = useState('bengaluru');
  const [cities, setCities] = useState<CityInfo[]>([]);
  const [facilityType, setFacilityType] = useState<FacilityType>('collection_centre');
  const [buffer, setBuffer] = useState(0);
  const [layers, setLayers] = useState<Layers>({ wards: null, roads: null, constraints: null });
  const [result, setResult] = useState<SuitabilityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [scenarioInputs, setScenarioInputs] = useState<ScenarioInputs | null>(null);
  const [budget, setBudget] = useState(400000);
  const [maxFacilities, setMaxFacilities] = useState(2);
  const [futureGrowth, setFutureGrowth] = useState(25);
  const [transportRate, setTransportRate] = useState(1.4);
  const [capacities, setCapacities] = useState<Record<string, number>>({});
  const [dismantlingCapacities, setDismantlingCapacities] = useState<Record<string, number>>({});
  const [fixedCosts, setFixedCosts] = useState<Record<string, number>>({});
  const [runs, setRuns] = useState<ScenarioRun[]>([]);
  const [scenarioLoading, setScenarioLoading] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([fetchCities(), fetchLayer('roads'), fetchLayer('constraints'), fetchScenarioInputs()])
      .then(([cityResponse, roads, constraints, inputs]) => {
        if (active) { setCities(cityResponse.items); setLayers((current) => ({ ...current, roads, constraints })); setScenarioInputs(inputs); setCapacities(inputs.capacities); setDismantlingCapacities(inputs.dismantling_capacities); setFixedCosts(inputs.fixed_costs); }
      })
      .catch((cause: Error) => { if (active) setError(cause.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    setLayers((current) => ({ ...current, wards: null }));
    fetchCityWards(cityId)
      .then((wards) => { if (active) setLayers((current) => ({ ...current, wards })); })
      .catch((cause: Error) => { if (active) setError(cause.message); });
    return () => { active = false; };
  }, [cityId]);

  useEffect(() => {
    let active = true;
    if (cityId !== 'bengaluru') {
      setResult(null);
      setLoading(false);
      return () => { active = false; };
    }
    setLoading(true);
    setError('');
    evaluateSuitability(facilityType, buffer)
      .then((value) => { if (active) setResult(value); })
      .catch((cause: Error) => { if (active) setError(cause.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [cityId, facilityType, buffer]);

  const candidateFeatures = cityId === 'bengaluru'
    ? runs.find((run) => run.results.scenario_type === 'optimized')?.results.geojson ?? result?.geojson ?? null
    : null;
  const rows = candidateFeatures?.features ?? [];
  const eligibleCount = rows.filter(({ properties }) => properties.eligible).length;
  const selectedCapacities = facilityType === 'collection_centre' ? capacities : dismantlingCapacities;
  const annualDemand = scenarioInputs
    ? Object.values(scenarioInputs.demand_by_ward).reduce((sum, value) => sum + value, 0)
    : 0;
  const projectedDemand = Math.max(annualDemand, annualDemand * (1 + futureGrowth / 100));
  const totalCandidateCapacity = Object.values(selectedCapacities).reduce((sum, value) => sum + value, 0);
  const demandExceedsCapacity = projectedDemand > totalCandidateCapacity;
  const selectedCity = cities.find((city) => city.city_id === cityId);
  const mapLayers = cityId === 'bengaluru' ? layers : { ...layers, roads: null, constraints: null };
  const sourcedPopulation = layers.wards?.features.reduce((sum, feature) => {
    const value = feature.properties.population_estimate;
    return sum + (typeof value === 'number' ? value : 0);
  }, 0) ?? 0;

  const executeScenarios = async () => {
    if (!scenarioInputs || !result) return;
    setScenarioLoading(true);
    setError('');
    try {
      const groupId = crypto.randomUUID();
      const rankedEligible = rows.filter(({ properties }) => properties.eligible)
        .sort((a, b) => Number(a.properties.rank) - Number(b.properties.rank));
      const baselineSites: string[] = [];
      let baselineFixedCost = 0;
      for (const { properties } of rankedEligible) {
        if (baselineSites.length >= maxFacilities) break;
        const candidateId = properties.candidate_id;
        const cost = fixedCosts[candidateId];
        if (!Number.isFinite(cost) || cost < 0 || baselineFixedCost + cost > budget) continue;
        baselineSites.push(candidateId);
        baselineFixedCost += cost;
      }
      const base = { group_id: groupId, facility_type: facilityType,
        input_data_status: scenarioInputs.data_status,
        demand_by_ward: scenarioInputs.demand_by_ward, fixed_costs: fixedCosts,
        capacities: selectedCapacities, budget, max_facilities: maxFacilities,
        transport_cost_per_tonne_km: transportRate, unserved_penalty_per_tonne: 1000000,
        criteria_weights: result.weights, constraint_types: ['synthetic_waterbody', 'synthetic_sensitive_use'],
        constraint_buffer_m: buffer };
      const baseline = await runScenario({ ...base, scenario_type: 'baseline', label: 'Baseline', baseline_facility_ids: baselineSites });
      const optimized = await runScenario({ ...base, scenario_type: 'optimized', label: 'Optimized' });
      const future = await runScenario({ ...base, scenario_type: 'future_demand', label: `Future +${futureGrowth}%`, future_growth_percent: futureGrowth });
      await compareScenarios([baseline.run_id, optimized.run_id, future.run_id]);
      setRuns([baseline, optimized, future]);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setScenarioLoading(false);
    }
  };

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand-mark">EW</div>
        <div><div className="eyebrow">CITY CIRCULAR MATERIALS PLANNER</div><h1>E-waste facility planner</h1></div>
        <label className="city-select">City / boundary
          <select aria-label="City / boundary" value={cityId} onChange={(event) => { setCityId(event.target.value); setRuns([]); }}>
            {cities.map((city) => <option key={city.city_id} value={city.city_id}>{city.name}</option>)}
            {!cities.length && <option value="bengaluru">Greater Bengaluru</option>}
          </select>
        </label>
        <div className="demo-pill"><span /> {cityId === 'bengaluru' ? 'Sourced wards | synthetic analysis layers' : 'Sourced Mumbai wards | population estimate'}</div>
      </header>
      <nav className="planner-nav" aria-label="Planner sections">
        <a href="#site-selection" onClick={scrollToSection('site-selection')}>Site selection</a>
        <a href="#scenario-lab" onClick={scrollToSection('scenario-lab')}>Network scenarios</a>
        <a href="#facility-design" onClick={scrollToSection('facility-design')}>Facility layout</a>
        {cityId === 'bengaluru' && <a href="#scenario-reports" onClick={scrollToSection('scenario-reports')}>Reports</a>}
      </nav>

      <section className="intro-row" id="site-selection">
        <div><div className="eyebrow">{cityId === 'bengaluru' ? 'SITE SELECTION / 01' : 'CITY SPATIAL DATA'}</div><h2>{cityId === 'bengaluru' ? 'Compare candidate locations' : 'Explore Mumbai ward boundaries'}</h2><p>{cityId === 'bengaluru' ? 'Review normalized criteria and configured constraints before planning a network.' : 'Inspect sourced BMC administrative wards and attributed 2023 population estimates.'}</p></div>
        {cityId === 'bengaluru' && <label className="facility-select">Facility model
          <select value={facilityType} onChange={(event) => {
            const next = event.target.value as FacilityType;
            setFacilityType(next);
            if (scenarioInputs) setFixedCosts(next === 'collection_centre' ? scenarioInputs.fixed_costs : scenarioInputs.dismantling_fixed_costs);
          }}>
            <option value="collection_centre">Collection centre</option>
            <option value="dismantling_facility">Dismantling facility</option>
          </select>
        </label>}
      </section>

      {error && <div className="error-banner" role="alert">API error: {error} · Start the backend with <code>uvicorn app.main:app --reload</code> from <code>backend</code>.</div>}

      {selectedCity && <section className="assumptions city-provenance">
        <div><span className="eyebrow">ACTIVE CITY DATA</span><strong>{selectedCity.boundary.feature_count} ward polygons | {selectedCity.boundary.source_year ?? 'vintage not stated'}</strong></div>
        <ul>
          <li>Boundary: {selectedCity.boundary.source}; {selectedCity.boundary.licence}; {selectedCity.boundary.crs}.</li>
          {selectedCity.population && <li>Ward population attribute: {selectedCity.population.source_year ?? 'year not stated'}; summed value {sourcedPopulation.toLocaleString()} people. Population is not e-waste demand.</li>}
          {selectedCity.population?.limitations && <li>{selectedCity.population.limitations}</li>}
          <li>{cityId === 'bengaluru' ? 'Candidate sites, roads, constraints and demand are still synthetic Bengaluru demo layers; they are not operational against Mumbai.' : 'Only ward boundaries and BMC 2023 population estimates are loaded for Mumbai. Candidate parcels, road network, constraints and ward-level e-waste demand are not available, so suitability and facility scenarios are disabled for this city.'}</li>
        </ul>
      </section>}

      <section className="workspace">
        <div className="map-panel">
          <div className="panel-heading"><div><span className="eyebrow">SPATIAL CONTEXT</span><h3>{cityId === 'bengaluru' ? 'Candidate sites & constraints' : 'Mumbai ward boundaries'}</h3></div>{cityId === 'bengaluru' && <div className="legend"><span className="dot selected" /> Selected <span className="dot eligible" /> Eligible <span className="dot excluded" /> Excluded</div>}</div>
          <FacilityMap {...mapLayers} candidates={candidateFeatures} cityId={cityId} />
          {loading && <div className="map-status" role="status">Loading GIS layers and scoring candidates…</div>}
          {!loading && rows.length === 0 && <div className="empty-state">{cityId === 'bengaluru' ? 'No candidate sites are available for this facility model.' : 'Showing sourced municipal ward boundaries. No Mumbai candidate sites are loaded.'}</div>}
          <div className="map-foot"><span>Ward boundaries: {selectedCity?.boundary.status ?? 'loading'}</span><span>{cityId === 'bengaluru' ? 'Roads, constraints and candidate points: synthetic demo | WGS 84' : 'Map shows ward boundaries only | WGS 84'}</span></div>
        </div>

        {cityId === 'bengaluru' ? <aside className="results-panel">
          <div className="panel-heading"><div><span className="eyebrow">RANKED REVIEW</span><h3>Suitability results</h3></div><span className="count-badge">{eligibleCount} eligible</span></div>
          <div className="score-summary"><span>Weighted suitability</span><strong>0–100</strong><small>Min-max normalized · cost criteria reversed</small></div>
          <label className="buffer-control">Environmental exclusion buffer <strong>{buffer} m</strong>
            <input type="range" min="0" max="1000" step="50" value={buffer} onChange={(event) => setBuffer(Number(event.target.value))} />
            <small>Editable analysis assumption. No regulatory distance is implied.</small>
          </label>
          {loading && <div className="empty-state">Calculating suitability…</div>}
          {!loading && rows.length > 0 && <div className="candidate-list">
            {rows.map(({ properties }) => <article className={`candidate-card ${properties.eligible ? '' : 'is-excluded'}`} key={properties.candidate_id}>
              <div className="rank-box">{properties.eligible ? `#${properties.rank}` : '×'}</div>
              <div className="candidate-main"><div className="candidate-title">{properties.candidate_id}<span>{properties.eligible ? 'Eligible' : 'Excluded'}</span></div>
                {properties.eligible ? <div className="meter"><span style={{ width: `${properties.score}%` }} /></div> : <div className="reason">{properties.exclusion_reasons.join(' · ')}</div>}
                <details className="candidate-breakdown"><summary>Score breakdown</summary>
                  {Object.keys(result?.criteria_directions ?? {}).map((criterion) => {
                    const normalized = properties[`normalized_${criterion}`];
                    const contribution = properties[`contribution_${criterion}`];
                    return <div key={criterion}><span>{criterion.replaceAll('_', ' ')}</span><small>
                      {typeof normalized === 'number' ? `${normalized.toFixed(1)} / 100` : '—'}
                      {typeof contribution === 'number' ? ` · weighted ${contribution.toFixed(1)}` : ''}
                    </small></div>;
                  })}
                </details>
              </div>
              <strong className="candidate-score">{properties.score.toFixed(1)}</strong>
            </article>)}
          </div>}
          <div className="weight-block"><div className="subheading">MODEL WEIGHTS</div>
            {result && Object.entries(result.weights).map(([criterion, weight]) => <div className="weight-row" key={criterion}><span>{criterion.replaceAll('_', ' ')}</span><strong>{(weight * 100).toFixed(0)}%</strong></div>)}
            {result?.ahp && <small className={result.ahp.consistency_acceptable ? 'consistent' : 'inconsistent'}>AHP consistency ratio {result.ahp.consistency_ratio.toFixed(3)} · {result.ahp.consistency_acceptable ? 'acceptable' : 'review comparisons'}</small>}
          </div>
        </aside> : <aside className="results-panel city-not-ready">
          <div className="panel-heading"><div><span className="eyebrow">CITY DATA STATUS</span><h3>Mumbai ward map</h3></div></div>
          <div className="score-summary"><span>Ward population total</span><strong>{sourcedPopulation.toLocaleString()}</strong><small>BMC mid-year estimate for 2023. Not an e-waste quantity.</small></div>
          <p>Real Mumbai boundaries and population attributes are visible on the map. Site ranking and network simulation are unavailable until Mumbai candidate locations, road data, environmental constraints and e-waste demand are sourced and validated.</p>
        </aside>}
      </section>

      {result && <section className="assumptions"><div><span className="eyebrow">DATA & METHOD</span><strong>{result.data_status.replaceAll('_', ' ')}</strong></div><ul>{result.assumptions.slice(-3).map((assumption) => <li key={assumption}>{assumption}</li>)}</ul></section>}
      {cityId === 'bengaluru' ? <section className="scenario-panel" id="scenario-lab">
        <div className="panel-heading"><div><span className="eyebrow">NETWORK SIMULATION</span><h3>Compare facility scenarios</h3></div>
          {scenarioInputs?.synthetic && <span className="demo-pill"><span /> Synthetic estimates</span>}</div>
        <p>{scenarioInputs?.assumption ?? 'Loading scenario inputs…'}</p>
        <div className="scenario-controls">
          <label>Fixed-cost budget (INR)<input aria-label="Fixed-cost budget (INR)" type="number" min="0" value={budget} onChange={(e) => setBudget(Number(e.target.value))} /></label>
          <label>Maximum facilities<input aria-label="Maximum facilities" type="number" min="0" max="20" value={maxFacilities} onChange={(e) => setMaxFacilities(Number(e.target.value))} /></label>
          <label>Future demand change (%)<input aria-label="Future demand change (%)" type="number" min="-100" value={futureGrowth} onChange={(e) => setFutureGrowth(Number(e.target.value))} /></label>
          <div className="scenario-capacity-threshold"><span>Maximum candidate capacity</span><strong>{totalCandidateCapacity.toLocaleString()} tonnes/year</strong><small>Sum of the current facility capacities shown below. Budget, facility limit, eligibility and routing can lower the capacity available in a run.</small></div>
          <label>Transport rate (INR / tonne-km)<input aria-label="Transport rate (INR / tonne-km)" type="number" min="0" step="0.1" value={transportRate} onChange={(e) => setTransportRate(Number(e.target.value))} /></label>
          {Object.entries(fixedCosts).map(([id, value]) => <label key={`cost-${id}`}>{id} fixed cost (INR)
            <input aria-label={`${id} fixed cost (INR)`} type="number" min="0" value={value}
              onChange={(e) => setFixedCosts((current) => ({ ...current, [id]: Number(e.target.value) }))} /></label>)}
          {Object.entries(selectedCapacities).map(([id, value]) => <label key={`capacity-${id}`}>{id} capacity (tonnes/year)
            <input aria-label={`${id} capacity (tonnes/year)`} type="number" min="0" value={value}
              onChange={(e) => {
                const update = facilityType === 'collection_centre' ? setCapacities : setDismantlingCapacities;
                update((current) => ({ ...current, [id]: Number(e.target.value) }));
              }} /></label>)}
        </div>
        {demandExceedsCapacity && <div role="alert" className="error-banner">
          Projected annual demand ({projectedDemand.toFixed(1)} tonnes) exceeds the total capacity of all current candidates ({totalCandidateCapacity.toFixed(1)} tonnes/year). Full service is impossible with these capacity inputs; you may still run the scenarios to see the unserved demand.
        </div>}
        {!demandExceedsCapacity && <p className="inline-note">Capacity threshold is calculated from the configured candidate facilities, not a fixed city-wide or regulatory limit.</p>}
        <button type="button" disabled={!scenarioInputs || !result || scenarioLoading} onClick={executeScenarios}>
          {scenarioLoading ? 'Calculating network scenarios…' : 'Run baseline, optimized and future scenarios'}
        </button>
        {runs.length > 0 && <div className="scenario-results" aria-live="polite">
          {runs.map((run) => <article key={run.run_id} className="scenario-card"><div className="eyebrow">{run.parameters.label as string}</div>
            <strong>{run.results.service_coverage_percent.toFixed(0)}% covered</strong>
            <span>{run.results.selected_facilities.length} facilities · {run.results.unserved_tonnes.toFixed(1)} t unserved</span>
            <span>INR {Math.round(run.results.total_estimated_operating_cost).toLocaleString()} estimated scenario cost</span>
            <span>{run.results.transport_distance_km.toFixed(1)} km average · {run.results.transport_tonne_km.toFixed(1)} tonne-km · {run.results.capacity_utilization_percent.toFixed(0)}% capacity used</span>
          </article>)}
          <div className="scenario-ranking"><strong>Optimized site ranking</strong>{(runs[1]?.results.candidate_scores ?? []).map((candidate) =>
            <div key={candidate.candidate_id}>{candidate.rank ? `#${candidate.rank}` : 'Excluded'} · {candidate.candidate_id} · {candidate.suitability_score.toFixed(1)}
              {candidate.exclusion_reasons.length > 0 && <small> — {candidate.exclusion_reasons.join('; ')}</small>}</div>)}</div>
          {runs[1]?.results.feasibility_explanation.map((reason) => <div className="reason" key={reason}>{reason}</div>)}
        </div>}
      </section> : <section className="scenario-panel" id="scenario-lab"><div className="panel-heading"><div><span className="eyebrow">NETWORK SIMULATION</span><h3>Mumbai scenarios unavailable</h3></div></div><p>Scenario calculations are disabled because Mumbai does not yet have verified demand, candidate costs and capacities, or a validated road network in this project.</p></section>}
      {cityId === 'bengaluru' && <section className="reports-panel" id="scenario-reports" aria-labelledby="reports-heading">
        <div className="panel-heading"><div><span className="eyebrow">EXPORTS</span><h3 id="reports-heading">Reports</h3></div></div>
        {runs[1] ? <div className="report-actions">
          <strong>Saved scenario group reports</strong>
          <a href={scenarioReportUrl(runs[1].run_id, 'pdf')}>Download PDF report</a>
          <a href={scenarioReportUrl(runs[1].run_id, 'csv')}>Download CSV data</a>
        </div> : <div className="empty-state">
          Run the baseline, optimized and future scenarios above to generate downloadable PDF and CSV reports.
          <a href="#scenario-lab">Go to scenario controls</a>
        </div>}
      </section>}
      <FacilityDesigner />
      <footer>Planning support · Scores are relative to this loaded dataset and its documented assumptions.</footer>
    </main>
  );
}
