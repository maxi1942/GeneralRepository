// Prize wheel: draws weighted slices on a canvas and spins to a chosen slice.
const COLORS = ['#ff6b6b', '#ffa94d', '#ffd43b', '#69db7c', '#38d9a9', '#4dabf7', '#9775fa', '#f783ac'];

export function pickWeighted(prizes, rand = Math.random) {
  const total = prizes.reduce((s, p) => s + p.weight, 0);
  let r = rand() * total;
  for (let i = 0; i < prizes.length; i++) {
    r -= prizes[i].weight;
    if (r < 0) return i;
  }
  return prizes.length - 1;
}

export class Wheel {
  constructor(canvas) {
    this.canvas = canvas;
    this.rotation = 0;     // degrees, cumulative
    this.prizes = [];
  }

  // Slices in degrees, clockwise from the top (where the pointer is).
  slices() {
    const total = this.prizes.reduce((s, p) => s + p.weight, 0) || 1;
    let start = 0;
    return this.prizes.map((p, i) => {
      const size = (p.weight / total) * 360;
      const slice = { start, end: start + size, color: COLORS[i % COLORS.length], prize: p };
      start += size;
      return slice;
    });
  }

  draw(prizes) {
    this.prizes = prizes;
    const dpr = window.devicePixelRatio || 1;
    const css = this.canvas.clientWidth || 300;
    this.canvas.width = this.canvas.height = css * dpr;
    const ctx = this.canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    const c = css / 2, r = c - 4;
    ctx.clearRect(0, 0, css, css);
    if (!prizes.length) {
      ctx.fillStyle = '#8884';
      ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.fill();
      return;
    }
    const rad = (deg) => ((deg - 90) * Math.PI) / 180;
    for (const s of this.slices()) {
      ctx.beginPath();
      ctx.moveTo(c, c);
      ctx.arc(c, c, r, rad(s.start), rad(s.end));
      ctx.closePath();
      ctx.fillStyle = s.color;
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 2;
      ctx.stroke();

      ctx.save();
      ctx.translate(c, c);
      ctx.rotate(rad((s.start + s.end) / 2));
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#1b1b1b';
      const label = `${s.prize.name.length > 16 ? s.prize.name.slice(0, 15) + '…' : s.prize.name} ${s.prize.emoji}`;
      ctx.font = `600 ${Math.max(10, Math.round(css / 28))}px system-ui, sans-serif`;
      ctx.fillText(label, r - 12, 0);
      ctx.restore();
    }
    ctx.beginPath(); ctx.arc(c, c, css / 14, 0, Math.PI * 2);
    ctx.fillStyle = '#fff'; ctx.fill();
  }

  // Animate so the pointer stops inside slice `index`. Resolves when finished.
  spinTo(index) {
    const s = this.slices()[index];
    const margin = (s.end - s.start) * 0.15;
    const target = s.start + margin + Math.random() * (s.end - s.start - 2 * margin);
    const current = ((this.rotation % 360) + 360) % 360;
    // Rotating clockwise by R puts wheel angle (-R mod 360) under the pointer.
    let delta = (360 - target) - current;
    delta = ((delta % 360) + 360) % 360;
    this.rotation += 360 * 6 + delta;
    this.canvas.style.transition = 'transform 4.5s cubic-bezier(0.15, 0.85, 0.2, 1)';
    this.canvas.style.transform = `rotate(${this.rotation}deg)`;
    return new Promise((res) => setTimeout(res, 4700));
  }
}
