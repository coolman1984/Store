// Code 128 (set B) barcodes as SVG: the receipt number and the product labels. No library, no network.
// Patterns are the standard 11-module bar/space strings, value 0..105 (103-105 are the start codes); the stop is 13 modules.
const PATTERNS = '11011001100 11001101100 11001100110 10010011000 10010001100 10001001100 10011001000 10011000100 10001100100 11001001000 11001000100 11000100100 10110011100 10011011100 10011001110 10111001100 10011101100 10011100110 11001110010 11001011100 11001001110 11011100100 11001110100 11101101110 11101001100 11100101100 11100100110 11101100100 11100110100 11100110010 11011011000 11011000110 11000110110 10100011000 10001011000 10001000110 10110001000 10001101000 10001100010 11010001000 11000101000 11000100010 10110111000 10110001110 10001101110 10111011000 10111000110 10001110110 11101110110 11010001110 11000101110 11011101000 11011100010 11011101110 11101011000 11101000110 11100010110 11101101000 11101100010 11100011010 11101111010 11001000010 11110001010 10100110000 10100001100 10010110000 10010000110 10000101100 10000100110 10110010000 10110000100 10011010000 10011000010 10000110100 10000110010 11000010010 11001010000 11110111010 11000010100 10001111010 10100111100 10010111100 10010011110 10111100100 10011110100 10011110010 11110100100 11110010100 11110010010 11011011110 11011110110 11110110110 10101111000 10100011110 10001011110 10111101000 10111100010 11110101000 11110100010 10111011110 10111101110 11101011110 11110101110 11010000100 11010010000 11010011100'.split(' ');
const STOP = '1100011101011';
const START_B = 104;

export function code128Modules(text) {
  const values = [START_B];
  for (const ch of String(text)) {
    const c = ch.codePointAt(0);
    if (c < 32 || c > 126) throw new RangeError('Code 128 set B holds printable ASCII only');
    values.push(c - 32);
  }
  let sum = values[0];
  for (let i = 1; i < values.length; i++) sum += values[i] * i;
  values.push(sum % 103);
  return values.map((v) => PATTERNS[v]).join('') + STOP;
}

/** An SVG string (use raw() to place it). `height` is the bar height in px; each module is `module` px wide; 10 modules quiet zone each side. */
export function barcodeSVG(text, { height = 40, module = 1.6, label = '' } = {}) {
  let bits;
  try { bits = code128Modules(text); } catch { return ''; }
  const quiet = 10;
  const width = (bits.length + quiet * 2) * module;
  const bars = [];
  for (let i = 0; i < bits.length;) {
    if (bits[i] === '0') { i++; continue; }
    let j = i;
    while (j < bits.length && bits[j] === '1') j++;
    bars.push(`M${((i + quiet) * module).toFixed(2)} 0h${((j - i) * module).toFixed(2)}v${height}h-${((j - i) * module).toFixed(2)}z`);
    i = j;
  }
  const alt = label || String(text);
  return `<svg class="barcode" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width.toFixed(2)} ${height}" width="${width.toFixed(0)}" height="${height}" role="img" aria-label="${alt.replace(/[<>&"]/g, '')}" preserveAspectRatio="none"><path d="${bars.join('')}" fill="#000"/></svg>`;
}
