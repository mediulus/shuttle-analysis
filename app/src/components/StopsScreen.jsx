import { useState } from 'react';
import { ROUTES, ACCENT } from '../stops.js';
import { BackIcon, StarIcon } from './Icons.jsx';

function StopRow({ route, stop, fav, onOpen, onToggle }) {
  return (
    <div className="row">
      <button type="button" className="row-main" onClick={() => onOpen(route.id, stop.id)}>
        <div>
          <div className="row-name">{stop.name}</div>
          <div className="row-sub">{route.name}</div>
        </div>
        <div>
          <div className="row-eta">{stop.eta} min</div>
          <div className="row-range">{stop.lo}–{stop.hi} likely</div>
        </div>
      </button>
      <button
        type="button"
        className="row-star"
        aria-pressed={fav}
        aria-label={`${fav ? 'Remove' : 'Add'} ${stop.name} ${fav ? 'from' : 'to'} favorites`}
        onClick={() => onToggle(stop.id)}
      >
        <StarIcon filled={fav} color={ACCENT} />
      </button>
    </div>
  );
}

export default function StopsScreen({ route, favs, onToggleFav, onBack, onOpenStop }) {
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();

  // Favorites span every route; "All stops" lists only the route being viewed.
  const favRows = ROUTES.flatMap((r) => r.stops.filter((s) => favs[s.id]).map((s) => ({ route: r, stop: s })));
  const allStops = route.stops.filter((s) => !q || s.name.toLowerCase().includes(q));

  return (
    <div className="screen screen--stops" style={{ '--accent': route.color }}>
      <header className="stops-head">
        <button type="button" className="back-btn" aria-label="Back to map" onClick={onBack}>
          <BackIcon />
        </button>
        <h1>Stops</h1>
      </header>

      <div className="search">
        <label htmlFor="q">SEARCH STOPS</label>
        <input
          id="q"
          type="text"
          placeholder="Silber Way, Pacific, Mass Ave..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <div className="list">
        <div className="section-title">
          <StarIcon size={16} filled color={ACCENT} />
          FAVORITES
        </div>
        {favRows.length === 0 && <div className="empty">Tap the star on a stop to pin it here.</div>}
        {favRows.map(({ route: r, stop }) => (
          <StopRow key={stop.id} route={r} stop={stop} fav onOpen={onOpenStop} onToggle={onToggleFav} />
        ))}

        <div className="section-title section-title--all">ALL STOPS · {route.name.toUpperCase()}</div>
        {allStops.length === 0 && <div className="empty">No stops match that search.</div>}
        {allStops.map((s) => (
          <StopRow key={s.id} route={route} stop={s} fav={!!favs[s.id]} onOpen={onOpenStop} onToggle={onToggleFav} />
        ))}
      </div>
    </div>
  );
}
