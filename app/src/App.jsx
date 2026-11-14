import { useState } from 'react';
import MapScreen from './components/MapScreen.jsx';
import StopsScreen from './components/StopsScreen.jsx';
import { DEFAULT_ROUTE, getRoute } from './stops.js';

export default function App() {
  const [screen, setScreen] = useState('map');
  const [routeId, setRouteId] = useState(DEFAULT_ROUTE);
  const [selected, setSelected] = useState('s7');
  const [favs, setFavs] = useState({ s3: true, s7: true });

  const route = getRoute(routeId);

  const toggleFav = (id) => setFavs((f) => ({ ...f, [id]: !f[id] }));
  const changeRoute = (id) => {
    setRouteId(id);
    setSelected(getRoute(id).stops[0].id);
  };
  const openStop = (rId, stopId) => {
    setRouteId(rId);
    setSelected(stopId);
    setScreen('map');
  };

  return (
    <div className="phone">
      {screen === 'map' ? (
        <MapScreen
          route={route}
          selected={selected}
          onSelect={setSelected}
          onChangeRoute={changeRoute}
          favs={favs}
          onToggleFav={toggleFav}
          onOpenStops={() => setScreen('stops')}
        />
      ) : (
        <StopsScreen
          route={route}
          favs={favs}
          onToggleFav={toggleFav}
          onBack={() => setScreen('map')}
          onOpenStop={openStop}
        />
      )}
    </div>
  );
}
