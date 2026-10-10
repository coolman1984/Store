// The Al-Store mark: two equal bars (books that balance) resting on a fulcrum (the shop's scale).
// One drawing for every size; colours come from CSS classes, so it follows the theme and the surface it sits on.
import { raw, esc } from './ui.js';

/** tone: 'light' = navy tile for light surfaces, 'dark' = ivory tile for the navy rail and dark surfaces */
export const mark = (tone = 'light', label = '') => raw(`<svg class="mark mark-${tone}" viewBox="0 0 48 48" ${label ? `role="img" aria-label="${esc(label)}"` : 'aria-hidden="true"'}>
<rect class="mk-tile" width="48" height="48" rx="12"/>
<rect class="mk-beam" x="11" y="12" width="26" height="4.5" rx="2.25"/>
<rect class="mk-pan" x="11" y="19.5" width="26" height="4.5" rx="2.25"/>
<path class="mk-beam mk-foot" d="M24 26 32 36H16Z"/></svg>`);
