import { useState } from 'react';
import { ROUTES, ACCENT } from '../stops.js';
import MapView from './MapView.jsx';
import Drawer from './Drawer.jsx';
import { MenuIcon, StarIcon, ChevronDownIcon } from './Icons.jsx';

export default function MapScreen({ route, selected, onSelect, onChangeRoute, favs, onToggleFav, onOpenStops }) {
  const [drawer, setDrawer] = useState(false);
  const [routeMenu, setRouteMenu] = useState(false);
  const cur = route.stops.find((s) => s.id === selected) ?? route.stops[0];
  const isFav = !!favs[cur.id];

  const pickRoute = (id) => {
    setRouteMenu(false);
    onChangeRoute(id);
  };

  return (
    <div className="screen screen--map" style={{ '--accent': route.color }}>
      <MapView route={route} selected={cur.id} onSelect={onSelect} />

      <div className="topbar">
        <button type="button" className="fab" aria-label="Open menu" onClick={() => setDrawer(true)}>
          <MenuIcon />
        </button>
        <button
          type="button"
          className="pill pill--button"
          aria-haspopup="true"
          aria-expanded={routeMenu}
          aria-label={`Route: ${route.name}. Change route`}
          onClick={() => setRouteMenu((v) => !v)}
        >
          <span className="route-dot" />
          <span className="pill-name">{route.name}</span>
          <ChevronDownIcon />
        </button>
      </div>

      {routeMenu && (
        <div className="route-menu" role="group" aria-label="Choose a route">
          {ROUTES.map((r) => (
            <button
              key={r.id}
              type="button"
              className="route-option"
              aria-pressed={r.id === route.id}
              onClick={() => pickRoute(r.id)}
            >
              <span className="route-dot" style={{ background: r.color }} />
              <span className="grow">{r.name}</span>
              {r.id === route.id && <span className="route-check">Showing</span>}
            </button>
          ))}
        </div>
      )}

      <section className="sheet" aria-label="Selected stop">
        <div className="sheet-handle" />
        <div className="sheet-head">
          <div style={{ minWidth: 0 }}>
            <div className="eyebrow">STOP</div>
            <div className="stop-name">{cur.name}</div>
          </div>
          <button
            type="button"
            className="fav-btn"
            aria-label="Favorite this stop"
            aria-pressed={isFav}
            onClick={() => onToggleFav(cur.id)}
          >
            <StarIcon filled={isFav} color={ACCENT} />
          </button>
        </div>

        <div className="eta-card">
          <div>
            <div className="eta-route">
              <span className="route-dot" />
              {route.name}
            </div>
            <div className="eta-then">Then {cur.eta + 30} and {cur.eta + 60} min</div>
          </div>
          <div className="eta-right">
            <div className="eta-big">
              <span className="eta-num">{cur.eta}</span>
              <span className="eta-unit">min</span>
            </div>
          </div>
        </div>

        <button type="button" className="cta" onClick={onOpenStops}>View all stops</button>
      </section>

      {drawer && (
        <Drawer
          onClose={() => setDrawer(false)}
          onOpenRoutes={() => {
            setDrawer(false);
            setRouteMenu(true);
          }}
          onOpenStops={() => {
            setDrawer(false);
            onOpenStops();
          }}
        />
      )}
    </div>
  );
}
