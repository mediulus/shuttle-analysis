import { CloseIcon, MailIcon, RouteIcon, PinIcon, StarIcon } from './Icons.jsx';

export default function Drawer({ onClose, onOpenStops, onOpenRoutes }) {
  return (
    <div className="drawer-root">
      <nav className="drawer" aria-label="Main menu">
        <div className="drawer-head">
          <div>
            <img className="drawer-logo" src="/mit-logo.webp" alt="MIT" />
            <div className="drawer-title">Shuttles</div>
          </div>
          <button type="button" className="icon-btn" aria-label="Close menu" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>

        <button type="button" className="nav-item" onClick={onClose}>
          <MailIcon />
          <span className="grow">Messages</span>
          <span className="badge">2</span>
        </button>
        <button type="button" className="nav-item" onClick={onOpenRoutes}>
          <RouteIcon />
          <span className="grow">Routes</span>
        </button>
        <button type="button" className="nav-item" onClick={onOpenStops}>
          <PinIcon />
          <span className="grow">Stops</span>
        </button>
        <button type="button" className="nav-item" onClick={onOpenStops}>
          <StarIcon />
          <span className="grow">Favorites</span>
        </button>

      </nav>
      <button type="button" className="scrim" aria-label="Close menu" onClick={onClose} />
    </div>
  );
}
