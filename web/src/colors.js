// Escala divergente azul <-> rojo con punto medio neutro (convención de las "warming stripes").
// Paso por OKLab-ish simple: interpolación lineal entre paradas ya elegidas a mano en la rampa de la paleta.
const COLD = [[0x10, 0x42, 0x81], [0x2a, 0x78, 0xd6], [0x86, 0xb6, 0xef]]; // fuerte -> suave
const MID = [0xea, 0xe8, 0xe3];
const WARM = [[0xf3, 0xa3, 0x85], [0xe3, 0x49, 0x48], [0x8f, 0x1b, 0x22]]; // suave -> fuerte

const lerp = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

function ramp(stops, t) {
  const x = Math.min(Math.max(t, 0), 1) * (stops.length - 1);
  const i = Math.min(Math.floor(x), stops.length - 2);
  return lerp(stops[i], stops[i + 1], x - i);
}

/** v en unidades de la variable; max = valor que alcanza el extremo de la escala (simétrico). */
export function diverging(v, max) {
  const t = Math.max(-1, Math.min(1, v / max));
  if (t >= 0) return ramp([MID, ...WARM], t);
  return ramp([MID, COLD[2], COLD[1], COLD[0]], -t);
}

export const css = (rgb) => `rgb(${rgb[0]} ${rgb[1]} ${rgb[2]})`;

export function gradientCss(max, steps = 24) {
  const stops = [];
  for (let i = 0; i <= steps; i++) {
    const v = -max + (2 * max * i) / steps;
    stops.push(`${css(diverging(v, max))} ${(i / steps) * 100}%`);
  }
  return `linear-gradient(90deg, ${stops.join(',')})`;
}

// Rampa secuencial para temperatura absoluta del suelo: gris-ciruela apagado -> naranja -> ámbar claro.
const HEAT = [[58, 46, 58], [150, 62, 66], [232, 106, 62], [252, 196, 108]];
export function heat(v, lo, hi) {
  return ramp(HEAT, (v - lo) / (hi - lo));
}
export function heatGradientCss(lo, hi, steps = 24) {
  const stops = [];
  for (let i = 0; i <= steps; i++) {
    stops.push(`${css(heat(lo + ((hi - lo) * i) / steps, lo, hi))} ${(i / steps) * 100}%`);
  }
  return `linear-gradient(90deg, ${stops.join(',')})`;
}
