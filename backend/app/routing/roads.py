"""Road-only shortest paths with explicit point-to-road access connectors."""
from __future__ import annotations

import math
from itertools import pairwise

import geopandas as gpd
import networkx as nx
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

METRIC_CRS = "EPSG:32643"


class RoadRouter:
    """Build a metric graph from linework and route points via nearest road vertices.

    Point-to-vertex connector lengths are reported independently; they are not
    represented as road distance. Disconnected graph pairs have no route.
    """
    def __init__(self, roads: gpd.GeoDataFrame):
        if roads.crs is None:
            raise ValueError("Road layer CRS is required")
        projected = roads.to_crs(METRIC_CRS)
        self.source_crs = roads.crs
        if projected.empty or projected.geometry.isna().any() or (~projected.geometry.is_valid).any():
            raise ValueError("Road layer must contain valid line geometries")
        merged = unary_union([geom for geom in projected.geometry if geom is not None])
        lines = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
        self.graph = nx.Graph()
        for line in lines:
            if not isinstance(line, LineString):
                continue
            coords = list(line.coords)
            for left, right in pairwise(coords):
                a, b = self._node(left), self._node(right)
                distance = math.dist(a, b)
                if distance:
                    self.graph.add_edge(a, b, distance_m=distance)
        if not self.graph:
            raise ValueError("Road layer has no routable line segments")

    @staticmethod
    def _node(coord):
        return (round(float(coord[0]), 2), round(float(coord[1]), 2))

    def snap(self, point: Point) -> tuple[tuple[float, float], float]:
        metric = gpd.GeoSeries([point], crs=self.source_crs).to_crs(METRIC_CRS).iloc[0]
        node = min(self.graph.nodes, key=lambda candidate: math.dist(candidate, (metric.x, metric.y)))
        return node, math.dist(node, (metric.x, metric.y))

    def distance(self, origin: Point, destination: Point) -> dict | None:
        source, source_connector = self.snap(origin)
        target, target_connector = self.snap(destination)
        try:
            network_m = nx.shortest_path_length(self.graph, source, target, weight="distance_m")
        except nx.NetworkXNoPath:
            return None
        return {"road_network_distance_m": float(network_m),
                "origin_access_connector_m": float(source_connector),
                "destination_access_connector_m": float(target_connector),
                "estimated_total_distance_m": float(network_m + source_connector + target_connector),
                "routing_method": "road_graph_plus_explicit_access_connectors"}
