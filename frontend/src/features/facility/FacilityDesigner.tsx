import { useEffect, useRef, useState } from 'react';
import { calculateFacilityDesign, downloadFacilityLayout, fetchFacilityDesignDefaults } from '../../lib/api';
import type { FacilityDesign, FacilityDesignInput } from '../../types/api';

const editableFields: Array<{ key: keyof FacilityDesignInput; label: string; step?: number }> = [
  { key: 'daily_throughput_tonnes_per_day', label: 'Daily throughput (tonnes/day)', step: 0.1 },
  { key: 'operating_days_per_year', label: 'Operating days/year', step: 1 },
  { key: 'storage_duration_days', label: 'Storage duration (days)', step: 0.5 },
  { key: 'plot_width_m', label: 'Plot width (m)', step: 1 },
  { key: 'plot_depth_m', label: 'Plot depth (m)', step: 1 },
  { key: 'receiving_area_m2_per_tpd', label: 'Receiving (m² per t/day)', step: 0.1 },
  { key: 'inspection_area_m2_per_tpd', label: 'Inspection (m² per t/day)', step: 0.1 },
  { key: 'dismantling_area_m2_per_tpd', label: 'Dismantling (m² per t/day)', step: 0.1 },
  { key: 'storage_area_m2_per_stored_tonne', label: 'Storage (m² per stored tonne)', step: 0.1 },
  { key: 'dispatch_area_m2_per_tpd', label: 'Dispatch (m² per t/day)', step: 0.1 },
  { key: 'circulation_fraction', label: 'Circulation fraction', step: 0.05 },
];
const colors = ['#c7e3d0', '#d5e0f4', '#ead9bc', '#e9cbc5', '#d0e2ea', '#e1e0c8'];

export function FacilityDesigner() {
  const [inputs, setInputs] = useState<FacilityDesignInput | null>(null);
  const [design, setDesign] = useState<FacilityDesign | null>(null);
  const [warning, setWarning] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const calculationId = useRef(0);
  const calculationTimer = useRef<number | null>(null);

  useEffect(() => {
    let active = true;
    fetchFacilityDesignDefaults().then(({ defaults, warning: note }) => {
      if (!active) return;
      setInputs(defaults); setWarning(note); setLoading(true);
    }).catch((cause: Error) => { if (active) setError(cause.message); });
    return () => { active = false; };
  }, []);

  const recalculate = async (nextInputs: FacilityDesignInput) => {
    const requestId = ++calculationId.current;
    setLoading(true); setError('');
    try {
      const nextDesign = await calculateFacilityDesign(nextInputs);
      if (requestId === calculationId.current) setDesign(nextDesign);
    } catch (cause) {
      if (requestId === calculationId.current) {
        setDesign(null);
        setError((cause as Error).message);
      }
    } finally {
      if (requestId === calculationId.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (!inputs) return;
    calculationTimer.current = window.setTimeout(() => { void recalculate(inputs); }, 300);
    return () => {
      if (calculationTimer.current !== null) window.clearTimeout(calculationTimer.current);
      calculationId.current += 1;
    };
  }, [inputs]);

  const update = (key: keyof FacilityDesignInput, value: number) => {
    setDesign(null);
    setLoading(true);
    setInputs((current) => current ? { ...current, [key]: value } : current);
  };

  const calculate = async () => {
    if (!inputs) return;
    if (calculationTimer.current !== null) window.clearTimeout(calculationTimer.current);
    await recalculate(inputs);
  };

  const exportPdf = async () => {
    if (!inputs) return;
    try { setError(''); await downloadFacilityLayout(inputs); }
    catch (cause) { setError((cause as Error).message); }
  };

  const detailWidth = design ? Math.max(...design.zones.map((zone) => zone.x_m + zone.width_m), 1) : 1;
  const detailDepth = design ? Math.max(...design.zones.map((zone) => zone.y_m + zone.depth_m), 1) : 1;

  return <section className="facility-designer" id="facility-design">
    <div className="section-heading"><div><span className="eyebrow">FACILITY CONCEPT / 03</span><h2>Size and arrange process zones</h2>
      <p>Change an assumption to refresh the dimension-aware conceptual layout and zone table automatically.</p></div>
      <span className="concept-pill">Conceptual · estimates only</span></div>
    {warning && <p className="inline-note">{warning}</p>}
    <div className="design-grid">
      <div className="design-controls">
        {inputs ? editableFields.map(({ key, label, step }) => <label key={key}>{label}
          <input aria-label={label} type="number" min="0" step={step} value={inputs[key]}
            onChange={(event) => update(key, Number(event.target.value))} />
        </label>) : <div className="empty-state">Loading facility assumptions…</div>}
        <button type="button" disabled={!inputs || loading} onClick={calculate}>{loading ? 'Calculating layout…' : 'Calculate facility layout'}</button>
        <button className="secondary-button" type="button" disabled={!design || loading} onClick={exportPdf}>Export layout PDF</button>
      </div>
      <div className="design-preview">
        {loading && <div className="empty-state" role="status">Sizing zones and checking the plot envelope…</div>}
        {error && <div role="alert" className="error-banner">Facility design: {error}</div>}
        {!loading && !error && design && <>
          <div className="design-kpis"><div><span>Annual throughput</span><strong>{design.annual_throughput_tonnes.toFixed(1)} t/year</strong></div>
            <div><span>Storage requirement</span><strong>{design.storage_capacity_tonnes.toFixed(1)} t</strong></div>
            <div><span>Required / envelope</span><strong>{design.required_area_m2.toFixed(1)} / {design.envelope_area_m2.toFixed(1)} m²</strong></div></div>
          <div className="layout-frame" role="img" aria-label={`Conceptual facility zones within ${design.envelope.width_m} by ${design.envelope.depth_m} metre plot`}>
            <svg viewBox={`-4 -4 ${design.envelope.width_m + 8} ${design.envelope.depth_m + 12}`} preserveAspectRatio="xMidYMid meet">
              <defs><pattern id="layout-grid" width="10" height="10" patternUnits="userSpaceOnUse"><path d="M 10 0 L 0 0 0 10" fill="none" stroke="#e4eae3" strokeWidth="0.08" /></pattern></defs>
              <rect x="0" y="0" width={design.envelope.width_m} height={design.envelope.depth_m} fill="url(#layout-grid)" />
              {design.zones.map((zone, index) => <g key={zone.zone_id}>
                <rect x={zone.x_m} y={zone.y_m} width={zone.width_m} height={zone.depth_m}
                  data-area-m2={zone.area_m2} aria-label={`${zone.label}, ${zone.width_m.toFixed(2)} by ${zone.depth_m.toFixed(2)} metres`}
                  fill={colors[index]} stroke="#54665b" strokeWidth={Math.max(design.envelope.width_m / 500, 0.08)} />
              </g>)}
              <rect x="0" y="0" width={design.envelope.width_m} height={design.envelope.depth_m} fill="none" stroke="#263b30" strokeWidth={Math.max(design.envelope.width_m / 300, 0.12)} />
              <text x={design.envelope.width_m / 2} y="-1.6" textAnchor="middle" fontSize="1.5" fill="#31473a">{design.envelope.width_m} m</text>
              <text x="-2.2" y={design.envelope.depth_m / 2} textAnchor="middle" fontSize="1.5" fill="#31473a" transform={`rotate(-90 -2.2 ${design.envelope.depth_m / 2})`}>{design.envelope.depth_m} m</text>
              <path d={`M 0 ${design.envelope.depth_m + 5} h ${Math.min(10, design.envelope.width_m)}`} stroke="#263b30" strokeWidth="0.35" />
              <text x={Math.min(10, design.envelope.width_m) / 2} y={design.envelope.depth_m + 7} textAnchor="middle" fontSize="1.4" fill="#31473a">{Math.min(10, design.envelope.width_m)} m scale</text>
            </svg>
          </div>
          <div className="layout-detail-heading"><strong>Zone detail (enlarged view)</strong><span>Enlarged to show zones; dimensions and geometry remain in metres.</span></div>
          <div className="layout-detail-frame" role="img" aria-label={`Enlarged conceptual zone detail, ${detailWidth.toFixed(1)} by ${detailDepth.toFixed(1)} metre extent`}>
            <svg viewBox={`-0.5 -0.5 ${detailWidth + 1} ${detailDepth + 2}`} preserveAspectRatio="xMidYMid meet">
              <defs><pattern id="layout-detail-grid" width="1" height="1" patternUnits="userSpaceOnUse"><path d="M 1 0 L 0 0 0 1" fill="none" stroke="#e4eae3" strokeWidth="0.012" /></pattern></defs>
              <rect x="0" y="0" width={detailWidth} height={detailDepth} fill="url(#layout-detail-grid)" />
              {design.zones.map((zone, index) => <g key={zone.zone_id}>
                <rect x={zone.x_m} y={zone.y_m} width={zone.width_m} height={zone.depth_m}
                  data-area-m2={zone.area_m2} aria-label={`${zone.label}, ${zone.width_m.toFixed(2)} by ${zone.depth_m.toFixed(2)} metres`}
                  fill={colors[index]} stroke="#54665b" strokeWidth="0.035" />
                {zone.width_m >= 1 && zone.depth_m >= 1 && <text x={zone.x_m + zone.width_m / 2} y={zone.y_m + zone.depth_m / 2}
                  textAnchor="middle" dominantBaseline="middle" fontSize={Math.min(0.72, zone.width_m * 0.55, zone.depth_m * 0.55)}
                  fill="#31473a" fontWeight="700">{index + 1}</text>}
              </g>)}
              <rect x="0" y="0" width={detailWidth} height={detailDepth} fill="none" stroke="#263b30" strokeWidth="0.05" />
              <path d={`M 0 ${detailDepth + 0.9} h 1`} stroke="#263b30" strokeWidth="0.04" />
              <text x="0.5" y={detailDepth + 1.35} textAnchor="middle" fontSize="0.32" fill="#31473a">1 m scale</text>
            </svg>
          </div>
          <div className="zone-table-wrap">
            <table className="zone-table">
              <thead><tr><th scope="col">#</th><th scope="col">Process zone</th><th scope="col">Width (m)</th><th scope="col">Depth (m)</th><th scope="col">Area (m²)</th></tr></thead>
              <tbody>{design.zones.map((zone, index) => <tr key={zone.zone_id}>
                <td><span className="zone-table-marker" style={{ background: colors[index] }}>{index + 1}</span></td>
                <th scope="row">{zone.label}</th><td>{zone.width_m.toFixed(2)}</td><td>{zone.depth_m.toFixed(2)}</td><td>{zone.area_m2.toFixed(1)}</td>
              </tr>)}</tbody>
            </table>
          </div>
          <p className="inline-note">Envelope {design.envelope.width_m} m × {design.envelope.depth_m} m; {design.remaining_area_m2.toFixed(1)} m² unallocated. Zones remain inside the configured envelope.</p>
          <p className="inline-note area-summary">Process zones: {(design.process_area_m2 ?? (design.required_area_m2 - (design.circulation_area_m2 ?? design.zones.find((zone) => zone.zone_id === 'circulation')?.area_m2 ?? 0))).toFixed(1)} m² · circulation (counted once): {(design.circulation_area_m2 ?? design.zones.find((zone) => zone.zone_id === 'circulation')?.area_m2 ?? 0).toFixed(1)} m² · unallocated: {design.remaining_area_m2.toFixed(1)} m² of {design.envelope_area_m2.toFixed(1)} m².</p>
          <p className="layout-circulation-note">Circulation is represented as one conceptual zone based on the configured fraction; it does not depict distributed aisles or access routes.</p>
          <p className="concept-warning">Conceptual planning only. This is not an engineering drawing, code review, fire plan, or regulatory approval.</p>
        </>}
        {!loading && !error && !design && <div className="empty-state">Enter assumptions and calculate a layout.</div>}
      </div>
    </div>
    {design && <details className="method-details"><summary>Area calculations and assumptions</summary><ul>{design.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></details>}
  </section>;
}
