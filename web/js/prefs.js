// Per-device preferences (language, theme, text size, motion, sound). Never business data.
const KEY = 'store.prefs';
const DEFAULTS = { lang: 'ar', theme: 'auto', size: 'm', motion: 'auto', sound: true };
let cache = null;

function load() {
  if (cache) return cache;
  try { cache = { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(KEY) || '{}')) }; } catch { cache = { ...DEFAULTS }; }
  return cache;
}

export const prefs = {
  get(k) { return load()[k]; },
  set(k, v) { load()[k] = v; try { localStorage.setItem(KEY, JSON.stringify(cache)); } catch { /* private window: keep in memory */ } apply(); },
  all() { return { ...load() }; },
};

export function apply() {
  const p = load();
  const root = document.documentElement;
  const dark = p.theme === 'night' || (p.theme === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
  root.dataset.theme = p.theme === 'contrast' ? 'contrast' : dark ? 'night' : 'day';
  root.dataset.size = p.size;
  if (p.motion === 'off') root.dataset.motion = 'off'; else delete root.dataset.motion;
}
