import { useEffect, useRef, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

// Free CARTO "Voyager" basemap (OpenStreetMap data). Attribution is shown by the map.
const STYLE_URL = 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json';
const EMPTY_LINE = { type: 'Feature', geometry: { type: 'LineString', coordinates: [] } };

const BUS_SVG =
  '<svg width="22" height="22" viewBox="-12 -12 24 24" aria-hidden="true"><rect x="-9" y="-8" width="18" height="13" rx="3" fill="#fff"/><rect x="-7" y="-6" width="14" height="5" rx="1" fill="#1B1B1B"/><circle cx="-4.5" cy="7" r="2" fill="#fff"/><circle cx="4.5" cy="7" r="2" fill="#fff"/></svg>';

function stopElement(stop, onPick) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'stop-btn';
  btn.setAttribute('aria-label', `${stop.name}, ${stop.eta} minutes`);
  btn.addEventListener('click', () => onPick(stop.id));
  const dot = document.createElement('span');
  dot.className = 'stop-dot';
  const label = document.createElement('span');
  label.className = `stop-label stop-label--${stop.side}`;
  label.textContent = stop.short;
  btn.append(dot, label);
  return btn;
}

export default function MapView({ route, selected, onSelect }) {
  const container = useRef(null);
  const mapRef = useRef(null);
  const stopMarkers = useRef([]);
  const shuttleMarker = useRef(null);
  const onSelectRef = useRef(onSelect);
  const [ready, setReady] = useState(false);
  onSelectRef.current = onSelect;

  // Create the map once.
  useEffect(() => {
    const map = new maplibregl.Map({
      container: container.current,
      style: STYLE_URL,
      center: [-71.0975, 42.355],
      zoom: 13.5,
      attributionControl: false,
    });
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
    map.on('load', () => {
      map.addSource('route', { type: 'geojson', data: EMPTY_LINE });
      map.addLayer({
        id: 'route-casing', type: 'line', source: 'route',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': '#ffffff', 'line-width': 10 },
      });
      map.addLayer({
        id: 'route-line', type: 'line', source: 'route',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': '#A31F34', 'line-width': 5 },
      });
      if (mapRef.current === map) setReady(true);
    });
    mapRef.current = map;
    return () => {
      stopMarkers.current = [];
      shuttleMarker.current = null;
      setReady(false);
      map.remove();
    };
  }, []);

  // Draw the selected route: line, stop markers, shuttle, and fit the view.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !map.getSource('route')) return;

    map.getSource('route').setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: route.line } });
    map.setPaintProperty('route-line', 'line-color', route.color);

    stopMarkers.current.forEach((m) => m.marker.remove());
    stopMarkers.current = route.stops.map((stop) => {
      const el = stopElement(stop, (id) => onSelectRef.current(id));
      const marker = new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat(stop.lngLat).addTo(map);
      return { id: stop.id, el, marker };
    });

    shuttleMarker.current?.remove();
    const bus = document.createElement('div');
    bus.className = 'shuttle';
    bus.innerHTML = BUS_SVG;
    shuttleMarker.current = new maplibregl.Marker({ element: bus, anchor: 'center' }).setLngLat(route.shuttle).addTo(map);

    const bounds = route.line.reduce((b, c) => b.extend(c), new maplibregl.LngLatBounds(route.line[0], route.line[0]));
    map.fitBounds(bounds, { padding: { top: 90, bottom: 300, left: 64, right: 64 }, maxZoom: 16, duration: 600 });
  }, [ready, route]);

  // Highlight the selected stop.
  useEffect(() => {
    stopMarkers.current.forEach(({ id, el }) => el.setAttribute('aria-pressed', String(id === selected)));
  }, [ready, route, selected]);

  return <div ref={container} className="map-view" />;
}
