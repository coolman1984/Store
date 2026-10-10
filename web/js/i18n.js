// Words on screen come from the two dictionaries only (web/i18n/ar.js, en.js). Arabic is the default and RTL.
import ar from '../i18n/ar.js';
import en from '../i18n/en.js';
import { prefs } from './prefs.js';

const DICTS = { ar, en };

export function lang() { return prefs.get('lang') === 'en' ? 'en' : 'ar'; }

// `{owed:money}` in a dictionary string asks for a named formatter (ui.js registers `money`): the server sends piasters, a person reads pounds.
const FORMATS = {};
export function format(name, fn) { FORMATS[name] = fn; }

export function t(key, vars) {
  const d = DICTS[lang()];
  let s = d[key] ?? en[key] ?? key;
  if (vars) s = s.replace(/\{(\w+)(?::(\w+))?\}/g, (m, k, f) => (vars[k] === undefined || vars[k] === null ? m : f && FORMATS[f] ? FORMATS[f](vars[k]) : vars[k]));
  return s;
}

export function has(key) { return key in DICTS[lang()]; }

export function applyLang() {
  const l = lang();
  document.documentElement.lang = l;
  document.documentElement.dir = l === 'ar' ? 'rtl' : 'ltr';
}

export function setLang(l) { prefs.set('lang', l); applyLang(); }

export { DICTS };
