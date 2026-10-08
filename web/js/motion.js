// Motion that explains, never decorates for its own sake (grammar learned in the Animation studio: one cause per change,
// spring-like ease-out, blur only while moving, exact rest state). Everything respects "reduce motion".
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.motion === 'off';
const fine = () => matchMedia('(pointer: fine)').matches;

/** Swap page content with the View Transitions API when the browser has it. */
export function transition(update) {
  if (!document.startViewTransition || reduced()) { update(); return Promise.resolve(); }
  return document.startViewTransition(update).finished.catch(() => {});
}

/** Numbers count up to their value (600 ms, ease-out expo). data-count holds the target; data-fmt picks money/number. */
export function countUp(root, format) {
  root.querySelectorAll('[data-count]').forEach((el) => {
    const target = Number(el.dataset.count);
    if (reduced() || !Number.isFinite(target)) { el.textContent = format(target, el.dataset.fmt); return; }
    const start = performance.now(), dur = 650;
    const step = (now) => {
      const u = Math.min(1, (now - start) / dur);
      const k = u === 1 ? 1 : 1 - Math.pow(2, -10 * u);
      el.textContent = format(Math.round(target * k), el.dataset.fmt);
      if (u < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

/** Dynamic sizes without inline style attributes (the page's Content-Security-Policy forbids them). */
export function hydrate(root) {
  root.querySelectorAll('[data-w]').forEach((el) => el.style.setProperty('--w', el.dataset.w));
}

/** A line chart draws itself once. */
export function drawLines(root) {
  if (reduced()) return;
  root.querySelectorAll('.chart .line').forEach((path) => {
    const len = path.getTotalLength ? path.getTotalLength() : 0;
    if (!len) return;
    path.style.strokeDasharray = `${len}`;
    path.style.strokeDashoffset = `${len}`;
    path.getBoundingClientRect();
    path.style.transition = 'stroke-dashoffset 600ms cubic-bezier(.2,.8,.2,1)';
    path.style.strokeDashoffset = '0';
  });
}

/** A product added to the cart "lands": a short scale pop on the target. */
export function pop(el) {
  if (!el || reduced()) return;
  el.animate([{ transform: 'scale(.96)', filter: 'brightness(1.25)' }, { transform: 'scale(1.02)' }, { transform: 'scale(1)', filter: 'none' }],
    { duration: 320, easing: 'cubic-bezier(.34,1.36,.64,1)' });
}

/** Shake a field that refused input (wrong code, wrong password). */
export function shake(el) {
  if (!el || reduced()) return;
  el.animate([{ transform: 'translateX(0)' }, { transform: 'translateX(-6px)' }, { transform: 'translateX(5px)' },
    { transform: 'translateX(-3px)' }, { transform: 'translateX(0)' }], { duration: 320, easing: 'ease-out' });
}

let audio;
/** A soft click when a scanned product is added (can be switched off in the preferences). */
export function tick(ok = true) {
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    const o = audio.createOscillator(), g = audio.createGain();
    o.type = 'sine';
    o.frequency.value = ok ? 1320 : 220;
    g.gain.setValueAtTime(0.0001, audio.currentTime);
    g.gain.exponentialRampToValueAtTime(ok ? 0.08 : 0.12, audio.currentTime + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + (ok ? 0.09 : 0.25));
    o.connect(g).connect(audio.destination);
    o.start();
    o.stop(audio.currentTime + 0.3);
  } catch { /* no sound device: silent */ }
}

export function after(root, format) {
  hydrate(root);
  countUp(root, format);
  drawLines(root);
}
