const base = { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };

const STAR = 'M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.9 6.8 19.7l1-5.9L3.5 9.7l5.9-.8z';

export const MenuIcon = ({ size = 22 }) => (
  <svg {...base} width={size} height={size}><path d="M4 7h16M4 12h16M4 17h16" /></svg>
);
export const ChevronDownIcon = ({ size = 18 }) => (
  <svg {...base} width={size} height={size}><path d="M6 9l6 6 6-6" /></svg>
);
export const CloseIcon = ({ size = 20 }) => (
  <svg {...base} width={size} height={size}><path d="M6 6l12 12M18 6L6 18" /></svg>
);
export const BackIcon = ({ size = 22 }) => (
  <svg {...base} width={size} height={size}><path d="M15 5l-7 7 7 7" /></svg>
);
export const MailIcon = ({ size = 24 }) => (
  <svg {...base} width={size} height={size}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></svg>
);
export const RouteIcon = ({ size = 24 }) => (
  <svg {...base} width={size} height={size}><circle cx="6" cy="18" r="2.2" /><circle cx="18" cy="6" r="2.2" /><path d="M8 18h6a3 3 0 0 0 0-6h-4a3 3 0 0 1 0-6h6" /></svg>
);
export const PinIcon = ({ size = 24 }) => (
  <svg {...base} width={size} height={size}><path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21z" /><circle cx="12" cy="9.5" r="2.5" /></svg>
);
export const StarIcon = ({ size = 22, filled = false, color }) => (
  <svg {...base} width={size} height={size} fill={filled ? color : 'none'} stroke={filled ? color : 'currentColor'}>
    <path d={STAR} />
  </svg>
);
