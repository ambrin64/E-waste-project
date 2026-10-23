import { useEffect } from 'react';
import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip, useMap } from 'react-leaflet';
import type { FeatureCollection } from '../../types/api';
import type { Feature, Point } from 'geojson';
import type { LatLngBoundsExpression } from 'leaflet';

type Props = {
  wards: FeatureCollection | null;
  roads: FeatureCollection | null;
  constraints: FeatureCollection | null;
  candidates: FeatureCollection | null;
};

function FitDemoBounds() {
  const map = useMap();
  useEffect(() => {
    map.fitBounds([[12.935, 77.495], [12.965, 77.605]] as LatLngBoundsExpression);
  }, [map]);
  return null;
}

export function FacilityMap({ wards, roads, constraints, candidates }: Props) {
  return (
    <MapContainer center={[12.95, 77.55]} zoom={13} scrollWheelZoom className="map-canvas">
      <FitDemoBounds />
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {wards && <GeoJSON data={wards as never} style={{ color: '#547f6b', weight: 1, fillOpacity: 0.05 }} />}
      {roads && <GeoJSON data={roads as never} style={{ color: '#aaa69d', weight: 3 }} />}
      {constraints && <GeoJSON data={constraints as never} style={{ color: '#cf795f', weight: 1, fillColor: '#dc927a', fillOpacity: 0.42 }} />}
      {candidates?.features.map((feature, index) => {
        if (feature.geometry.type !== 'Point') return null;
        const point = feature.geometry as Point;
        const [longitude, latitude] = point.coordinates as [number, number];
        const { properties } = feature as Feature<Point> & { properties: NonNullable<Feature<Point>['properties']> & {
          candidate_id: string; eligible: boolean; score: number; rank: number | null; exclusion_reasons: string[]; selected?: boolean; allocated_tonnes?: number;
        } };
        return (
          <CircleMarker
            key={`${properties.candidate_id}-${index}`}
            center={[latitude, longitude]}
            radius={properties.selected ? 10 : properties.eligible ? 7 : 6}
            pathOptions={{ color: properties.selected ? '#184e9c' : properties.eligible ? '#18684f' : '#a43e37', fillColor: properties.selected ? '#4b82d0' : properties.eligible ? '#54b38a' : '#d86d62', fillOpacity: 0.9, weight: 2 }}
          >
            <Tooltip>
              <strong>{properties.candidate_id}</strong><br />
              {properties.eligible ? `Eligible · ${properties.score.toFixed(1)} / 100 · rank ${properties.rank}` : `Excluded · ${properties.exclusion_reasons.join('; ')}`}
              {properties.selected && <><br />Selected · {properties.allocated_tonnes?.toFixed(1) ?? 0} tonnes/year allocated</>}
            </Tooltip>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
