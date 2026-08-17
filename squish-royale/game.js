/* Squish Royale — 3D battle royale prototype. Horizontal-plane aim only. */
(function () {
'use strict';

/* ---------------- utilities ---------------- */
const rand = (a, b) => a + Math.random() * (b - a);
const randInt = (a, b) => Math.floor(rand(a, b + 1));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const dist2d = (ax, az, bx, bz) => Math.hypot(ax - bx, az - bz);
const angleLerp = (a, b, t) => {
  let d = (b - a) % (Math.PI * 2);
  if (d > Math.PI) d -= Math.PI * 2;
  if (d < -Math.PI) d += Math.PI * 2;
  return a + d * t;
};
const $ = id => document.getElementById(id);

const BOT_NAMES = ['Pinto', 'Lima', 'Mungo', 'Fava', 'Navy', 'Adzuki', 'Garbanzo', 'Lentil',
  'Butterbean', 'Blackeye', 'Cannellini', 'Edamame', 'Haricot', 'Borlotti', 'Runner',
  'Snap', 'Wax', 'Chickpea', 'Soya'];

/* ---------------- persistent meta ---------------- */
const SAVE_KEY = 'squish-royale-save-v1';
const meta = Object.assign(
  { gold: 0, owned: ['w_pistol', 'c_red', 'c_blue', 'c_lime', 'h_none'], spawnWeapon: 'w_pistol', color: 'c_red', hat: 'h_none' },
  JSON.parse(localStorage.getItem(SAVE_KEY) || '{}')
);
const saveMeta = () => localStorage.setItem(SAVE_KEY, JSON.stringify(meta));

/* ---------------- shop catalog ---------------- */
const WEAPONS = {
  pistol:  { name: 'PISTOL',  tier: 0, dmg: 13, interval: 0.42, speed: 55, range: 34, mag: 12, reload: 1.1, pellets: 1, spread: 0.02, hue: 0xcfd6ff },
  smg:     { name: 'SMG',     tier: 1, dmg: 8,  interval: 0.13, speed: 58, range: 30, mag: 28, reload: 1.4, pellets: 1, spread: 0.075, hue: 0xffd24a },
  shotgun: { name: 'SHOTGUN', tier: 1, dmg: 8,  interval: 0.95, speed: 48, range: 20, mag: 6,  reload: 1.6, pellets: 5, spread: 0.16, hue: 0xff9d5c },
  rifle:   { name: 'RIFLE',   tier: 2, dmg: 15, interval: 0.27, speed: 65, range: 42, mag: 22, reload: 1.7, pellets: 1, spread: 0.03, hue: 0x7ddfff },
  sniper:  { name: 'RAILBEAN','tier': 3, dmg: 48, interval: 1.25, speed: 92, range: 70, mag: 5, reload: 1.9, pellets: 1, spread: 0.004, hue: 0xc07dff }
};
const SHOP_WEAPONS = [
  { id: 'w_pistol',  w: 'pistol',  em: '🔫', name: 'Pistol',   ds: 'Reliable all-rounder', price: 0 },
  { id: 'w_smg',     w: 'smg',     em: '💨', name: 'SMG',      ds: 'Spray up close, weak far', price: 250 },
  { id: 'w_shotgun', w: 'shotgun', em: '🧨', name: 'Shotgun',  ds: 'Huge burst, tiny range', price: 250 },
  { id: 'w_rifle',   w: 'rifle',   em: '🎯', name: 'Rifle',    ds: 'Steady mid-range poke', price: 450 }
];
const SHOP_COLORS = [
  { id: 'c_red',    hex: 0xe84545, price: 0 },   { id: 'c_blue',  hex: 0x4589e8, price: 0 },
  { id: 'c_lime',   hex: 0x7ed845, price: 0 },   { id: 'c_pink',  hex: 0xf06ec5, price: 100 },
  { id: 'c_orange', hex: 0xf2953a, price: 100 }, { id: 'c_teal',  hex: 0x3ad0c4, price: 100 },
  { id: 'c_purple', hex: 0x9a6cf0, price: 100 }, { id: 'c_black', hex: 0x3a3f52, price: 200 }
];
const SHOP_HATS = [
  { id: 'h_none',  em: '🚫', name: 'Bare',    ds: 'Clean bean', price: 0 },
  { id: 'h_cone',  em: '🚧', name: 'Cone',    ds: 'Certified hazard', price: 250 },
  { id: 'h_crown', em: '👑', name: 'Crown',   ds: 'Royale-ty', price: 400 },
  { id: 'h_sprout',em: '🌱', name: 'Sprout',  ds: 'Fresh from the pod', price: 150 }
];

/* ---------------- audio (tiny synth) ---------------- */
let AC = null, muted = false;
function audio() {
  if (!AC) { try { AC = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} }
  if (AC && AC.state === 'suspended') AC.resume();
  return AC;
}
function beep(freq, dur, type, vol, slide) {
  const ctx = audio(); if (!ctx || muted) return;
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = type || 'square'; o.frequency.setValueAtTime(freq, ctx.currentTime);
  if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, freq + slide), ctx.currentTime + dur);
  g.gain.setValueAtTime(vol || 0.08, ctx.currentTime);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + dur);
  o.connect(g).connect(ctx.destination); o.start(); o.stop(ctx.currentTime + dur);
}
const sfx = {
  shoot:  () => beep(rand(300, 340), 0.08, 'square', 0.05, -140),
  shotgun:() => beep(150, 0.16, 'sawtooth', 0.09, -90),
  hit:    () => beep(520, 0.06, 'triangle', 0.07, -180),
  hurt:   () => beep(140, 0.18, 'sawtooth', 0.09, -60),
  pickup: () => { beep(660, 0.07, 'sine', 0.07); setTimeout(() => beep(990, 0.09, 'sine', 0.07), 60); },
  kill:   () => { beep(523, 0.09, 'square', 0.07); setTimeout(() => beep(784, 0.12, 'square', 0.07), 80); },
  zone:   () => beep(220, 0.3, 'sine', 0.08, 40),
  win:    () => [523, 659, 784, 1047].forEach((f, i) => setTimeout(() => beep(f, 0.22, 'square', 0.08), i * 130)),
  lose:   () => [392, 330, 262].forEach((f, i) => setTimeout(() => beep(f, 0.26, 'triangle', 0.09), i * 160))
};

/* ---------------- three.js setup ---------------- */
const MAP_HALF = 110;          // playable half-extent
const app = $('app');
const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
app.insertBefore(renderer.domElement, app.firstChild);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x9fd4e8);
scene.fog = new THREE.Fog(0x9fd4e8, 90, 190);

const camera = new THREE.PerspectiveCamera(48, innerWidth / innerHeight, 0.5, 400);
const CAM_OFF = new THREE.Vector3(0, 34, 19);
function fitCamera() {
  // portrait phones need to sit higher to see combat ranges
  if (innerHeight > innerWidth) { CAM_OFF.set(0, 50, 26); camera.fov = 54; }
  else { CAM_OFF.set(0, 36, 20); camera.fov = 48; }
  camera.updateProjectionMatrix();
}
fitCamera();

scene.add(new THREE.HemisphereLight(0xdfefff, 0x6a9a50, 0.95));
const sun = new THREE.DirectionalLight(0xfff2d8, 1.15);
sun.position.set(40, 70, 25);
scene.add(sun);

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  fitCamera();
  renderer.setSize(innerWidth, innerHeight);
});

/* ---------------- world ---------------- */
const obstacles = [];   // {x, z, r}
(function buildWorld() {
  const ground = new THREE.Mesh(
    new THREE.CircleGeometry(MAP_HALF + 70, 48),
    new THREE.MeshLambertMaterial({ color: 0x86b85c })
  );
  ground.rotation.x = -Math.PI / 2;
  scene.add(ground);

  // darker grass patches
  {
    const g = new THREE.CircleGeometry(1, 12);
    const m = new THREE.MeshLambertMaterial({ color: 0x79ac52 });
    const inst = new THREE.InstancedMesh(g, m, 90);
    const mtx = new THREE.Matrix4(), q = new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0));
    for (let i = 0; i < 90; i++) {
      const s = rand(2, 7);
      mtx.compose(new THREE.Vector3(rand(-MAP_HALF, MAP_HALF), 0.02, rand(-MAP_HALF, MAP_HALF)), q, new THREE.Vector3(s, s, 1));
      inst.setMatrixAt(i, mtx);
    }
    scene.add(inst);
  }

  const place = (n, rMin, rMax, fn) => {
    for (let i = 0; i < n; i++) {
      let x, z, tries = 0;
      do { x = rand(-MAP_HALF + 6, MAP_HALF - 6); z = rand(-MAP_HALF + 6, MAP_HALF - 6); tries++; }
      while (tries < 20 && (Math.hypot(x, z) < 10 || obstacles.some(o => dist2d(x, z, o.x, o.z) < o.r + rMax + 2)));
      const r = rand(rMin, rMax);
      obstacles.push({ x, z, r });
      fn(x, z, r, i);
    }
  };

  // trees: instanced trunk + blob foliage
  {
    const N = 30;
    const trunk = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.55, 0.75, 3.4, 7), new THREE.MeshLambertMaterial({ color: 0x8a6242 }), N);
    const leaf = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1, 1), new THREE.MeshLambertMaterial({ color: 0x4e9a5e, flatShading: true }), N);
    const mtx = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(1, 1, 1);
    let i = 0;
    place(N, 1.0, 1.3, (x, z) => {
      mtx.compose(new THREE.Vector3(x, 1.7, z), q, up); trunk.setMatrixAt(i, mtx);
      const s = rand(2.2, 3.4);
      mtx.compose(new THREE.Vector3(x, 3.4 + s * 0.55, z), q, new THREE.Vector3(s, s * rand(0.9, 1.2), s)); leaf.setMatrixAt(i, mtx);
      i++;
    });
    scene.add(trunk, leaf);
  }
  // crates
  {
    const N = 24;
    const inst = new THREE.InstancedMesh(new THREE.BoxGeometry(3, 2.6, 3), new THREE.MeshLambertMaterial({ color: 0xc89b5e }), N);
    const mtx = new THREE.Matrix4(), s = new THREE.Vector3(1, 1, 1);
    let i = 0;
    place(N, 1.9, 1.9, (x, z) => {
      const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, rand(0, Math.PI), 0));
      mtx.compose(new THREE.Vector3(x, 1.3, z), q, s); inst.setMatrixAt(i, mtx); i++;
    });
    scene.add(inst);
  }
  // rocks
  {
    const N = 16;
    const inst = new THREE.InstancedMesh(new THREE.DodecahedronGeometry(1.6, 0), new THREE.MeshLambertMaterial({ color: 0xa7adc2, flatShading: true }), N);
    const mtx = new THREE.Matrix4();
    let i = 0;
    place(N, 1.5, 2.2, (x, z, r) => {
      const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(rand(0, 3), rand(0, 3), rand(0, 3)));
      mtx.compose(new THREE.Vector3(x, rand(0.2, 0.7), z), q, new THREE.Vector3(r / 1.4, r / 1.8, r / 1.4)); inst.setMatrixAt(i, mtx); i++;
    });
    scene.add(inst);
  }
})();

function collideWorld(px, pz, radius) {
  for (const o of obstacles) {
    const d = dist2d(px, pz, o.x, o.z), min = o.r + radius;
    if (d < min && d > 0.001) {
      px = o.x + (px - o.x) / d * min;
      pz = o.z + (pz - o.z) / d * min;
    }
  }
  const lim = MAP_HALF - 1;
  return [clamp(px, -lim, lim), clamp(pz, -lim, lim)];
}
function losBlocked(ax, az, bx, bz) {
  const dx = bx - ax, dz = bz - az, len = Math.hypot(dx, dz);
  if (len < 0.001) return false;
  const nx = dx / len, nz = dz / len;
  for (const o of obstacles) {
    const t = clamp((o.x - ax) * nx + (o.z - az) * nz, 0, len);
    if (dist2d(ax + nx * t, az + nz * t, o.x, o.z) < o.r * 0.9) return true;
  }
  return false;
}

/* ---------------- bean characters ---------------- */
const hatBuilders = {
  h_none: null,
  h_cone: () => new THREE.Mesh(new THREE.ConeGeometry(0.55, 1.1, 10), new THREE.MeshLambertMaterial({ color: 0xf2953a })),
  h_crown: () => {
    const g = new THREE.Group();
    const band = new THREE.Mesh(new THREE.CylinderGeometry(0.52, 0.58, 0.34, 8), new THREE.MeshLambertMaterial({ color: 0xffcf5c }));
    g.add(band);
    for (let i = 0; i < 4; i++) {
      const spike = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.4, 4), band.material);
      spike.position.set(Math.cos(i / 4 * Math.PI * 2) * 0.42, 0.32, Math.sin(i / 4 * Math.PI * 2) * 0.42);
      g.add(spike);
    }
    return g;
  },
  h_sprout: () => {
    const g = new THREE.Group();
    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.5, 5), new THREE.MeshLambertMaterial({ color: 0x4e9a5e }));
    stem.position.y = 0.2; g.add(stem);
    const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.22, 8, 6), stem.material);
    leaf.scale.set(1.6, 0.5, 0.8); leaf.position.y = 0.5; g.add(leaf);
    return g;
  }
};

function makeBean(colorHex, hatId) {
  const g = new THREE.Group();
  const bodyMat = new THREE.MeshLambertMaterial({ color: colorHex });
  const body = new THREE.Mesh(new THREE.SphereGeometry(0.95, 18, 14), bodyMat);
  body.scale.set(1, 1.32, 0.92);
  body.position.y = 1.22;
  g.add(body);
  // eyes (front = +Z of the group; we rotate group by yaw)
  const eyeMat = new THREE.MeshLambertMaterial({ color: 0xffffff });
  const pupilMat = new THREE.MeshLambertMaterial({ color: 0x23263c });
  for (const s of [-1, 1]) {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.21, 10, 8), eyeMat);
    eye.scale.set(1, 1.35, 0.55);
    eye.position.set(0.32 * s, 1.62, 0.78);
    g.add(eye);
    const pupil = new THREE.Mesh(new THREE.SphereGeometry(0.09, 8, 6), pupilMat);
    pupil.position.set(0.32 * s, 1.62, 0.92);
    g.add(pupil);
  }
  // feet
  const footMat = new THREE.MeshLambertMaterial({ color: new THREE.Color(colorHex).multiplyScalar(0.72) });
  for (const s of [-1, 1]) {
    const foot = new THREE.Mesh(new THREE.SphereGeometry(0.3, 8, 6), footMat);
    foot.scale.set(1, 0.55, 1.3);
    foot.position.set(0.42 * s, 0.16, 0.1);
    g.add(foot);
  }
  // antenna
  const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.55, 5), new THREE.MeshLambertMaterial({ color: 0x3a3f52 }));
  ant.position.set(0, 2.72, 0); g.add(ant);
  const bob = new THREE.Mesh(new THREE.SphereGeometry(0.13, 8, 6), new THREE.MeshLambertMaterial({ color: 0xffe08a }));
  bob.position.set(0, 3.02, 0); g.add(bob);
  // gun (held to the right, points +Z with group)
  const gun = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.26, 1.1), new THREE.MeshLambertMaterial({ color: 0x30344c }));
  gun.position.set(0.62, 1.25, 0.5);
  g.add(gun);
  // hat
  if (hatId && hatBuilders[hatId]) {
    const hat = hatBuilders[hatId]();
    hat.position.y = 2.62;
    g.add(hat);
  }
  // blob shadow
  const shadow = new THREE.Mesh(new THREE.CircleGeometry(0.85, 14), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.22 }));
  shadow.rotation.x = -Math.PI / 2; shadow.position.y = 0.03;
  g.add(shadow);
  return { group: g, body, gun };
}

/* ---------------- zone ---------------- */
const zone = { cx: 0, cz: 0, r: 105, tx: 0, tz: 0, tr: 105, phase: -1, timer: 0, shrinking: false, dps: 0 };
const ZONE_PHASES = [
  { wait: 18, shrink: 14, factor: 0.66, dps: 2 },
  { wait: 15, shrink: 12, factor: 0.62, dps: 4 },
  { wait: 13, shrink: 10, factor: 0.58, dps: 7 },
  { wait: 11, shrink: 9,  factor: 0.5,  dps: 12 },
  { wait: 9,  shrink: 8,  factor: 0.35, dps: 16 },
  { wait: 8,  shrink: 8,  factor: 0.15, dps: 22 }
];
const zoneWall = new THREE.Mesh(
  new THREE.CylinderGeometry(1, 1, 30, 64, 1, true),
  new THREE.MeshBasicMaterial({ color: 0x5ca8ff, transparent: true, opacity: 0.14, side: THREE.DoubleSide, depthWrite: false })
);
zoneWall.position.y = 15;
scene.add(zoneWall);
const zoneRing = new THREE.Mesh(
  new THREE.RingGeometry(0.985, 1, 96),
  new THREE.MeshBasicMaterial({ color: 0x5ca8ff, transparent: true, opacity: 0.85, side: THREE.DoubleSide })
);
zoneRing.rotation.x = -Math.PI / 2; zoneRing.position.y = 0.06;
scene.add(zoneRing);
const targetRing = new THREE.Mesh(
  new THREE.RingGeometry(0.97, 1, 96),
  new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.55, side: THREE.DoubleSide })
);
targetRing.rotation.x = -Math.PI / 2; targetRing.position.y = 0.07;
scene.add(targetRing);

function updateZoneMeshes() {
  zoneWall.position.x = zone.cx; zoneWall.position.z = zone.cz;
  zoneWall.scale.set(zone.r, 1, zone.r);
  zoneRing.position.x = zone.cx; zoneRing.position.z = zone.cz;
  zoneRing.scale.set(zone.r, zone.r, 1);
  targetRing.position.x = zone.tx; targetRing.position.z = zone.tz;
  targetRing.scale.set(zone.tr, zone.tr, 1);
  targetRing.visible = zone.tr < zone.r - 0.5;
}

/* ---------------- loot ---------------- */
const lootGeos = {
  weapon: new THREE.BoxGeometry(0.9, 0.9, 0.9),
  med: new THREE.BoxGeometry(0.85, 0.85, 0.85),
  armor: new THREE.OctahedronGeometry(0.62, 0)
};
let loot = [];   // {kind, weapon?, mesh, x, z, t}
function spawnLoot() {
  for (const l of loot) scene.remove(l.mesh);
  loot = [];
  const add = (kind, weapon) => {
    let x, z, tries = 0;
    do { x = rand(-MAP_HALF + 5, MAP_HALF - 5); z = rand(-MAP_HALF + 5, MAP_HALF - 5); tries++; }
    while (tries < 15 && obstacles.some(o => dist2d(x, z, o.x, o.z) < o.r + 1.5));
    let mesh;
    if (kind === 'weapon') {
      mesh = new THREE.Mesh(lootGeos.weapon, new THREE.MeshLambertMaterial({ color: WEAPONS[weapon].hue, emissive: WEAPONS[weapon].hue, emissiveIntensity: 0.25 }));
    } else if (kind === 'med') {
      mesh = new THREE.Mesh(lootGeos.med, new THREE.MeshLambertMaterial({ color: 0x5de0a6, emissive: 0x1d7a52, emissiveIntensity: 0.4 }));
    } else {
      mesh = new THREE.Mesh(lootGeos.armor, new THREE.MeshLambertMaterial({ color: 0x5ca8ff, emissive: 0x1c4f8a, emissiveIntensity: 0.4 }));
    }
    mesh.position.set(x, 1, z);
    scene.add(mesh);
    loot.push({ kind, weapon, mesh, x, z, t: rand(0, 6) });
  };
  const weaponPool = ['smg', 'smg', 'smg', 'shotgun', 'shotgun', 'shotgun', 'rifle', 'rifle', 'rifle', 'rifle', 'sniper', 'sniper'];
  for (let i = 0; i < 26; i++) add('weapon', weaponPool[randInt(0, weaponPool.length - 1)]);
  for (let i = 0; i < 20; i++) add('med');
  for (let i = 0; i < 14; i++) add('armor');
}
function animateLoot(dt) {
  for (const l of loot) {
    l.t += dt;
    l.mesh.position.y = 1 + Math.sin(l.t * 2.4) * 0.22;
    l.mesh.rotation.y += dt * 1.6;
  }
}

/* ---------------- agents ---------------- */
const AGENT_R = 1.05;
let agents = [];
let player = null;

function makeAgent(isPlayer, idx) {
  const colorHex = isPlayer
    ? SHOP_COLORS.find(c => c.id === meta.color).hex
    : SHOP_COLORS[randInt(0, SHOP_COLORS.length - 1)].hex;
  const bean = makeBean(colorHex, isPlayer ? meta.hat : (Math.random() < 0.12 ? 'h_cone' : 'h_none'));
  scene.add(bean.group);
  const a = {
    isPlayer, name: isPlayer ? 'You' : BOT_NAMES[idx % BOT_NAMES.length],
    x: 0, z: 0, yaw: 0, moveX: 0, moveZ: 0,
    hp: 100, armor: 0, alive: true,
    weapon: isPlayer ? SHOP_WEAPONS.find(s => s.id === meta.spawnWeapon).w : 'pistol',
    ammo: 0, cooldown: 0, reloading: 0,
    kills: 0, bean, hitFlash: 0, walkT: 0, zoneTick: 0,
    // bot brain
    skill: rand(0.35, 1), think: rand(0, 0.25), wx: 0, wz: 0, strafeDir: Math.random() < 0.5 ? 1 : -1,
    strafeT: 0, reactT: 0, target: null
  };
  a.ammo = WEAPONS[a.weapon].mag;
  return a;
}

function damageAgent(a, dmg, attacker) {
  if (!a.alive) return;
  if (a.armor > 0) {
    const absorbed = Math.min(a.armor, dmg * 0.6);
    a.armor -= absorbed; dmg -= absorbed;
  }
  a.hp -= dmg;
  a.hitFlash = 0.12;
  if (a.isPlayer) { sfx.hurt(); flashVignette(false); }
  if (a.hp <= 0) killAgent(a, attacker);
}

function killAgent(a, attacker) {
  a.alive = false;
  a.bean.group.visible = false;
  const attName = attacker ? attacker.name : 'the zone';
  addFeed(attacker, a);
  if (attacker && attacker.alive) attacker.kills++;
  if (attacker === player) {
    match.killGold += 25;
    toast('+25 🪙');
    sfx.kill();
  }
  // drop a med where they fell
  if (Math.random() < 0.5) {
    const mesh = new THREE.Mesh(lootGeos.med, new THREE.MeshLambertMaterial({ color: 0x5de0a6, emissive: 0x1d7a52, emissiveIntensity: 0.4 }));
    mesh.position.set(a.x, 1, a.z); scene.add(mesh);
    loot.push({ kind: 'med', mesh, x: a.x, z: a.z, t: 0 });
  }
  if (a.isPlayer) {
    match.placement = agents.filter(x => x.alive).length + 1;
    match.killedBy = attName;
    endMatch(false);
  } else if (player.alive && agents.filter(x => x.alive).length === 1) {
    match.placement = 1;
    endMatch(true);
  }
}

/* pickups */
function tryPickup(a) {
  for (let i = loot.length - 1; i >= 0; i--) {
    const l = loot[i];
    if (dist2d(a.x, a.z, l.x, l.z) > 1.7) continue;
    let take = false;
    if (l.kind === 'med' && a.hp < 100) { a.hp = Math.min(100, a.hp + 40); take = true; }
    else if (l.kind === 'armor' && a.armor < 100) { a.armor = Math.min(100, a.armor + 50); take = true; }
    else if (l.kind === 'weapon' && WEAPONS[l.weapon].tier > WEAPONS[a.weapon].tier) {
      a.weapon = l.weapon; a.ammo = WEAPONS[l.weapon].mag; a.reloading = 0; take = true;
      if (a.isPlayer) toast(WEAPONS[l.weapon].name + '!', true);
    }
    if (take) {
      scene.remove(l.mesh); loot.splice(i, 1);
      if (a.isPlayer) sfx.pickup();
    }
  }
}

/* ---------------- projectiles ---------------- */
const bulletGeo = new THREE.SphereGeometry(0.16, 6, 5);
const bulletMats = {};
let bullets = [];  // {x,z,dx,dz,speed,dmg,left,owner,mesh}
function fire(a) {
  const w = WEAPONS[a.weapon];
  if (a.cooldown > 0 || a.reloading > 0) return;
  if (a.ammo <= 0) { a.reloading = w.reload; return; }
  a.ammo--; a.cooldown = w.interval;
  if (a.ammo <= 0) a.reloading = w.reload;
  if (!bulletMats[a.weapon]) bulletMats[a.weapon] = new THREE.MeshBasicMaterial({ color: w.hue });
  for (let p = 0; p < w.pellets; p++) {
    const ang = a.yaw + (Math.random() - 0.5) * 2 * w.spread * Math.PI;
    const mesh = new THREE.Mesh(bulletGeo, bulletMats[a.weapon]);
    mesh.position.set(a.x + Math.sin(ang) * 1.3, 1.45, a.z + Math.cos(ang) * 1.3);
    scene.add(mesh);
    bullets.push({ x: mesh.position.x, z: mesh.position.z, dx: Math.sin(ang), dz: Math.cos(ang), speed: w.speed, dmg: w.dmg, left: w.range, owner: a, mesh });
  }
  if (a.isPlayer || dist2d(a.x, a.z, player.x, player.z) < 45) {
    (a.weapon === 'shotgun' ? sfx.shotgun : sfx.shoot)();
  }
  // muzzle kick on the bean
  a.bean.gun.position.z = 0.32;
}
function updateBullets(dt) {
  for (let i = bullets.length - 1; i >= 0; i--) {
    const b = bullets[i];
    const step = b.speed * dt;
    const sub = Math.max(1, Math.ceil(step / 1.2));
    let dead = false;
    for (let s = 0; s < sub && !dead; s++) {
      const d = step / sub;
      b.x += b.dx * d; b.z += b.dz * d; b.left -= d;
      if (b.left <= 0 || Math.abs(b.x) > MAP_HALF + 2 || Math.abs(b.z) > MAP_HALF + 2) { dead = true; break; }
      for (const o of obstacles) {
        if (dist2d(b.x, b.z, o.x, o.z) < o.r * 0.9) { dead = true; break; }
      }
      if (dead) break;
      for (const a of agents) {
        if (!a.alive || a === b.owner) continue;
        if (dist2d(b.x, b.z, a.x, a.z) < AGENT_R) {
          damageAgent(a, b.dmg, b.owner);
          if (b.owner === player) sfx.hit();
          dead = true; break;
        }
      }
    }
    if (dead) { scene.remove(b.mesh); bullets.splice(i, 1); }
    else b.mesh.position.set(b.x, 1.45, b.z);
  }
}

/* ---------------- bot AI ---------------- */
function botThink(a, dt) {
  a.think -= dt;
  if (a.think > 0) return;
  a.think = 0.22 + rand(0, 0.12);

  // find target
  let best = null, bestD = 46 * a.skill + 14;
  for (const o of agents) {
    if (o === a || !o.alive) continue;
    const d = dist2d(a.x, a.z, o.x, o.z);
    if (d < bestD && !losBlocked(a.x, a.z, o.x, o.z)) { best = o; bestD = d; }
  }
  if (best && !a.target) a.reactT = 0.25 + (1 - a.skill) * 0.5;
  a.target = best;

  const distToCenter = dist2d(a.x, a.z, zone.cx, zone.cz);
  const inDanger = distToCenter > zone.r - 9;

  if (inDanger) {
    // run for the safe zone
    const ang = Math.atan2(zone.cx - a.x, zone.cz - a.z) + rand(-0.4, 0.4);
    a.wx = zone.cx - Math.sin(ang) * zone.r * 0.4;
    a.wz = zone.cz - Math.cos(ang) * zone.r * 0.4;
  } else if (!a.target) {
    // loot run: meds if hurt, better weapon otherwise
    let want = null, wantD = 40;
    for (const l of loot) {
      const good = (l.kind === 'med' && a.hp < 65) || (l.kind === 'armor' && a.armor < 40) ||
                   (l.kind === 'weapon' && WEAPONS[l.weapon].tier > WEAPONS[a.weapon].tier);
      if (!good) continue;
      if (dist2d(l.x, l.z, zone.cx, zone.cz) > zone.tr + 4) continue;  // don't loot outside next zone
      const d = dist2d(a.x, a.z, l.x, l.z);
      if (d < wantD) { want = l; wantD = d; }
    }
    if (want) { a.wx = want.x; a.wz = want.z; }
    else if (dist2d(a.x, a.z, a.wx, a.wz) < 4 || (a.wx === 0 && a.wz === 0)) {
      const ang = rand(0, Math.PI * 2), rr = rand(0, Math.max(8, zone.tr * 0.85));
      a.wx = clamp(zone.tx + Math.sin(ang) * rr, -MAP_HALF + 4, MAP_HALF - 4);
      a.wz = clamp(zone.tz + Math.cos(ang) * rr, -MAP_HALF + 4, MAP_HALF - 4);
    }
  }
}
function botAct(a, dt) {
  a.reactT -= dt; a.strafeT -= dt;
  const w = WEAPONS[a.weapon];
  if (a.target && a.target.alive) {
    const t = a.target;
    const d = dist2d(a.x, a.z, t.x, t.z);
    // face target with error
    const err = (1.05 - a.skill) * 0.24;
    const aim = Math.atan2(t.x - a.x, t.z - a.z) + rand(-err, err);
    a.yaw = angleLerp(a.yaw, aim, 0.35);
    // keep a distance band, strafe
    if (a.strafeT < 0) { a.strafeT = rand(0.7, 1.6); a.strafeDir *= Math.random() < 0.75 ? -1 : 1; }
    const band = w.range * 0.62;
    const toward = d > band ? 1 : (d < band * 0.55 ? -1 : 0);
    const fx = Math.sin(a.yaw), fz = Math.cos(a.yaw);
    const sx = Math.cos(a.yaw) * a.strafeDir, sz = -Math.sin(a.yaw) * a.strafeDir;
    a.moveX = fx * toward * 0.8 + sx * 0.65;
    a.moveZ = fz * toward * 0.8 + sz * 0.65;
    if (a.reactT <= 0 && d < w.range * 0.95 && !losBlocked(a.x, a.z, t.x, t.z)) fire(a);
  } else {
    const d = dist2d(a.x, a.z, a.wx, a.wz);
    if (d > 1.5) {
      const ang = Math.atan2(a.wx - a.x, a.wz - a.z);
      a.yaw = angleLerp(a.yaw, ang, 0.18);
      a.moveX = Math.sin(a.yaw); a.moveZ = Math.cos(a.yaw);
    } else { a.moveX = 0; a.moveZ = 0; }
  }
}

/* ---------------- input ---------------- */
const input = { mx: 0, mz: 0, aimYaw: null, firing: false };
const keys = {};
addEventListener('keydown', e => { keys[e.code] = true; });
addEventListener('keyup', e => { keys[e.code] = false; });

let mouse = { x: 0, y: 0, down: false, used: false };
addEventListener('mousemove', e => { mouse.x = e.clientX; mouse.y = e.clientY; mouse.used = true; });
addEventListener('mousedown', e => { if (e.target.closest('.screen,button')) return; mouse.down = true; audio(); });
addEventListener('mouseup', () => { mouse.down = false; });

// touch twin-stick
const joyL = { id: null, ox: 0, oy: 0, dx: 0, dy: 0 };
const joyR = { id: null, ox: 0, oy: 0, dx: 0, dy: 0 };
const joyLEl = $('joyL'), joyREl = $('joyR');
const JOY_R = 52;
function joySet(el, j) {
  el.style.display = 'block';
  el.style.left = j.ox + 'px'; el.style.top = j.oy + 'px';
  el.querySelector('.knob').style.transform =
    `translate(calc(-50% + ${j.dx * JOY_R}px), calc(-50% + ${j.dy * JOY_R}px))`;
}
function handleTouch(e) {
  if (match.state !== 'playing') return;
  e.preventDefault();
  audio();
  for (const t of e.changedTouches) {
    if (e.type === 'touchstart') {
      const left = t.clientX < innerWidth / 2;
      const j = left ? joyL : joyR;
      if (j.id !== null) continue;
      j.id = t.identifier; j.ox = t.clientX; j.oy = t.clientY; j.dx = 0; j.dy = 0;
      joySet(left ? joyLEl : joyREl, j);
    } else if (e.type === 'touchmove') {
      for (const j of [joyL, joyR]) {
        if (j.id !== t.identifier) continue;
        const dx = t.clientX - j.ox, dy = t.clientY - j.oy;
        const m = Math.hypot(dx, dy) || 1;
        const cl = Math.min(m, JOY_R);
        j.dx = dx / m * (cl / JOY_R); j.dy = dy / m * (cl / JOY_R);
        joySet(j === joyL ? joyLEl : joyREl, j);
      }
    } else {
      for (const j of [joyL, joyR]) {
        if (j.id === t.identifier) { j.id = null; j.dx = 0; j.dy = 0; (j === joyL ? joyLEl : joyREl).style.display = 'none'; }
      }
    }
  }
}
for (const ev of ['touchstart', 'touchmove', 'touchend', 'touchcancel'])
  app.addEventListener(ev, handleTouch, { passive: false });

const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -1.4);
const raycaster = new THREE.Raycaster();
const hitPoint = new THREE.Vector3();
function readInput() {
  // movement
  let mx = 0, mz = 0;
  if (keys.KeyW || keys.ArrowUp) mz -= 1;
  if (keys.KeyS || keys.ArrowDown) mz += 1;
  if (keys.KeyA || keys.ArrowLeft) mx -= 1;
  if (keys.KeyD || keys.ArrowRight) mx += 1;
  if (joyL.id !== null) { mx = joyL.dx; mz = joyL.dy; }
  const m = Math.hypot(mx, mz);
  if (m > 1) { mx /= m; mz /= m; }
  input.mx = mx; input.mz = mz;

  // aim: right stick wins, else mouse
  if (joyR.id !== null && Math.hypot(joyR.dx, joyR.dy) > 0.25) {
    input.aimYaw = Math.atan2(joyR.dx, joyR.dy);   // screen right = +x world, screen down = +z world
    input.firing = Math.hypot(joyR.dx, joyR.dy) > 0.4;
  } else if (mouse.used) {
    raycaster.setFromCamera(
      { x: (mouse.x / innerWidth) * 2 - 1, y: -(mouse.y / innerHeight) * 2 + 1 }, camera);
    if (raycaster.ray.intersectPlane(groundPlane, hitPoint)) {
      input.aimYaw = Math.atan2(hitPoint.x - player.x, hitPoint.z - player.z);
    }
    input.firing = mouse.down;
  } else {
    input.firing = false;
  }
}

/* ---------------- HUD ---------------- */
const hpFill = $('hp-fill'), armorFill = $('armor-fill');
const vignette = $('vignette');
let vignetteT = 0;
function flashVignette(isZone) {
  vignette.classList.toggle('zone', !!isZone);
  vignette.style.opacity = 0.9;
  vignetteT = 0.35;
}
function toast(text, elim) {
  const el = document.createElement('div');
  el.className = 'toast' + (elim ? ' elim' : '');
  el.textContent = text;
  $('toasts').appendChild(el);
  setTimeout(() => el.remove(), 1150);
}
function addFeed(attacker, victim) {
  const feed = $('killfeed');
  const el = document.createElement('div');
  el.className = 'feed';
  const an = attacker ? attacker.name : 'The zone';
  el.innerHTML = `<b class="${attacker === player ? 'me' : ''}">${an}</b> squished <b class="${victim === player ? 'me' : ''}">${victim.name}</b>`;
  feed.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, 3600);
  while (feed.children.length > 4) feed.firstChild.remove();
}

const mm = $('minimap').getContext('2d');
function drawMinimap() {
  const S = mm.canvas.width, K = S / (MAP_HALF * 2);
  mm.clearRect(0, 0, S, S);
  mm.fillStyle = 'rgba(20,26,52,0.85)'; mm.fillRect(0, 0, S, S);
  const px = x => (x + MAP_HALF) * K, pz = z => (z + MAP_HALF) * K;
  // current zone
  mm.strokeStyle = 'rgba(92,168,255,0.9)'; mm.lineWidth = 1.6;
  mm.beginPath(); mm.arc(px(zone.cx), pz(zone.cz), zone.r * K, 0, 7); mm.stroke();
  // target zone
  if (zone.tr < zone.r - 0.5) {
    mm.strokeStyle = 'rgba(255,255,255,0.75)';
    mm.setLineDash([3, 3]);
    mm.beginPath(); mm.arc(px(zone.tx), pz(zone.tz), zone.tr * K, 0, 7); mm.stroke();
    mm.setLineDash([]);
  }
  // player arrow
  if (player) {
    mm.save();
    mm.translate(px(player.x), pz(player.z));
    mm.rotate(Math.atan2(Math.sin(player.yaw), Math.cos(player.yaw)));
    mm.fillStyle = '#FFC94A';
    mm.beginPath(); mm.moveTo(0, -5); mm.lineTo(3.6, 4); mm.lineTo(-3.6, 4); mm.closePath(); mm.fill();
    mm.restore();
  }
}

function updateHUD() {
  $('alive').textContent = agents.filter(a => a.alive).length;
  $('kills').textContent = player.kills;
  $('gold-hud').textContent = meta.gold + match.killGold;
  const w = WEAPONS[player.weapon];
  $('weapon-name').textContent = w.name;
  $('ammo').textContent = player.ammo + ' / ' + w.mag;
  $('reload-tag').style.display = player.reloading > 0 ? 'inline' : 'none';
  hpFill.style.width = Math.max(0, player.hp) + '%';
  hpFill.classList.toggle('low', player.hp <= 35);
  armorFill.style.width = player.armor + '%';
}

/* ---------------- zone messages ---------------- */
const zoneMsg = $('zone-msg');
function setZoneMsg() {
  if (!player.alive) return;
  const outside = dist2d(player.x, player.z, zone.cx, zone.cz) > zone.r;
  if (outside) { zoneMsg.innerHTML = '<span class="warn">⚠ GET TO THE ZONE</span>'; return; }
  if (zone.shrinking) zoneMsg.innerHTML = '<span class="warn">ZONE SHRINKING</span>';
  else if (zone.phase < ZONE_PHASES.length) zoneMsg.innerHTML = `<span class="safe">zone shrinks in ${Math.ceil(zone.timer)}s</span>`;
  else zoneMsg.textContent = '';
}

/* ---------------- match flow ---------------- */
const match = { state: 'menu', killGold: 0, placement: 20, killedBy: '', time: 0 };

function startMatch() {
  // clear old
  for (const a of agents) scene.remove(a.bean.group);
  for (const b of bullets) scene.remove(b.mesh);
  agents = []; bullets = [];
  spawnLoot();

  zone.cx = 0; zone.cz = 0; zone.r = 105;
  zone.tx = 0; zone.tz = 0; zone.tr = 105;
  zone.phase = 0; zone.timer = ZONE_PHASES[0].wait; zone.shrinking = false; zone.dps = ZONE_PHASES[0].dps;
  updateZoneMeshes();

  match.killGold = 0; match.placement = 20; match.killedBy = ''; match.time = 0;

  // spawn ring
  const startAng = rand(0, Math.PI * 2);
  for (let i = 0; i < 20; i++) {
    const a = makeAgent(i === 0, i - 1);
    const ang = startAng + (i / 20) * Math.PI * 2 + rand(-0.08, 0.08);
    const rr = rand(88, 100);
    [a.x, a.z] = collideWorld(Math.sin(ang) * rr, Math.cos(ang) * rr, AGENT_R);
    a.yaw = ang + Math.PI;
    a.wx = a.x; a.wz = a.z;
    a.bean.group.position.set(a.x, 0, a.z);
    a.bean.group.rotation.y = a.yaw;
    agents.push(a);
  }
  player = agents[0];

  $('killfeed').innerHTML = '';
  $('menu').classList.remove('on');
  $('results').classList.remove('on');
  $('shop').classList.remove('on');
  $('hud').style.display = 'block';
  $('mute').style.display = 'block';
  updateHUD(); drawMinimap();

  // countdown
  match.state = 'countdown';
  const cd = $('countdown');
  cd.style.display = 'flex';
  let n = 3;
  cd.textContent = n;
  beep(440, 0.12, 'square', 0.07);
  const iv = setInterval(() => {
    n--;
    if (n > 0) { cd.textContent = n; beep(440, 0.12, 'square', 0.07); }
    else {
      clearInterval(iv);
      cd.textContent = 'GO!';
      beep(880, 0.25, 'square', 0.09);
      setTimeout(() => { cd.style.display = 'none'; }, 550);
      match.state = 'playing';
    }
  }, 800);
}

function endMatch(won) {
  if (match.state === 'over') return;
  match.state = 'over';
  (won ? sfx.win : sfx.lose)();
  const placeGold = match.placement === 1 ? 100 : match.placement <= 5 ? 50 : match.placement <= 10 ? 25 : 0;
  const total = match.killGold + placeGold;
  meta.gold += total;
  saveMeta();
  setTimeout(() => {
    $('hud').style.display = 'none';
    joyLEl.style.display = 'none'; joyREl.style.display = 'none';
    joyL.id = joyR.id = null;
    const rp = $('res-place');
    rp.textContent = won ? '🏆 VICTORY!' : '#' + match.placement;
    rp.classList.toggle('win', won);
    $('res-sub').textContent = won
      ? 'Last bean standing. The pod is proud.'
      : `Squished by ${match.killedBy} · ${agents.filter(a => a.alive).length} beans remained`;
    $('res-kills').textContent = player.kills;
    $('res-kill-gold').textContent = '+' + match.killGold;
    $('res-place-gold').textContent = '+' + placeGold;
    $('res-total').textContent = '+' + total;
    $('results').classList.add('on');
  }, won ? 1400 : 1200);
}

/* ---------------- zone update ---------------- */
function updateZone(dt) {
  if (zone.phase >= ZONE_PHASES.length) { /* final zone holds */ }
  else {
    zone.timer -= dt;
    const ph = ZONE_PHASES[zone.phase];
    if (!zone.shrinking && zone.timer <= 0) {
      zone.shrinking = true;
      zone.timer = ph.shrink;
      zone.startR = zone.r; zone.startX = zone.cx; zone.startZ = zone.cz;
      sfx.zone();
    } else if (zone.shrinking) {
      const t = clamp(1 - zone.timer / ph.shrink, 0, 1);
      zone.r = lerp(zone.startR, zone.tr, t);
      zone.cx = lerp(zone.startX, zone.tx, t);
      zone.cz = lerp(zone.startZ, zone.tz, t);
      if (zone.timer <= 0) {
        zone.shrinking = false;
        zone.phase++;
        if (zone.phase < ZONE_PHASES.length) {
          const nph = ZONE_PHASES[zone.phase];
          zone.timer = nph.wait; zone.dps = nph.dps;
          const nr = zone.r * nph.factor;
          const off = (zone.r - nr) * rand(0.2, 0.85), ang = rand(0, Math.PI * 2);
          zone.tx = clamp(zone.cx + Math.sin(ang) * off, -MAP_HALF + nr * 0.3, MAP_HALF - nr * 0.3);
          zone.tz = clamp(zone.cz + Math.cos(ang) * off, -MAP_HALF + nr * 0.3, MAP_HALF - nr * 0.3);
          zone.tr = nr;
        }
      }
    } else if (zone.phase === 0 && zone.tr === zone.r) {
      // set first target once
      const ph0 = ZONE_PHASES[0];
      const nr = zone.r * ph0.factor;
      const off = (zone.r - nr) * rand(0.1, 0.7), ang = rand(0, Math.PI * 2);
      zone.tx = clamp(Math.sin(ang) * off, -60, 60);
      zone.tz = clamp(Math.cos(ang) * off, -60, 60);
      zone.tr = nr;
    }
  }
  updateZoneMeshes();
  // zone damage
  for (const a of agents) {
    if (!a.alive) continue;
    if (dist2d(a.x, a.z, zone.cx, zone.cz) > zone.r) {
      a.zoneTick -= dt;
      if (a.zoneTick <= 0) {
        a.zoneTick = 0.5;
        const wasAlive = a.alive;
        if (a.isPlayer) flashVignette(true);
        // zone damage bypasses armor
        a.hp -= zone.dps * 0.5;
        a.hitFlash = 0.1;
        if (a.hp <= 0 && wasAlive) killAgent(a, null);
      }
    } else a.zoneTick = 0;
  }
}

/* ---------------- agent update ---------------- */
const SPEED = 10.5, BOT_SPEED = 9.6;
function updateAgents(dt) {
  // separation (cheap O(n^2))
  for (let i = 0; i < agents.length; i++) {
    const a = agents[i]; if (!a.alive) continue;
    for (let j = i + 1; j < agents.length; j++) {
      const b = agents[j]; if (!b.alive) continue;
      const d = dist2d(a.x, a.z, b.x, b.z);
      if (d < 1.9 && d > 0.001) {
        const push = (1.9 - d) / 2, nx = (a.x - b.x) / d, nz = (a.z - b.z) / d;
        a.x += nx * push; a.z += nz * push;
        b.x -= nx * push; b.z -= nz * push;
      }
    }
  }
  for (const a of agents) {
    if (!a.alive) continue;
    if (a.isPlayer) {
      a.moveX = input.mx; a.moveZ = input.mz;
      if (input.aimYaw !== null) a.yaw = input.aimYaw;
      else if (Math.hypot(a.moveX, a.moveZ) > 0.1) a.yaw = angleLerp(a.yaw, Math.atan2(a.moveX, a.moveZ), 0.25);
      if (input.firing) fire(a);
    } else {
      botThink(a, dt);
      botAct(a, dt);
    }
    const spd = a.isPlayer ? SPEED : BOT_SPEED;
    let nx = a.x + a.moveX * spd * dt, nz = a.z + a.moveZ * spd * dt;
    [nx, nz] = collideWorld(nx, nz, AGENT_R);
    a.x = nx; a.z = nz;
    a.cooldown -= dt;
    if (a.reloading > 0) {
      a.reloading -= dt;
      if (a.reloading <= 0) { a.ammo = WEAPONS[a.weapon].mag; a.reloading = 0; }
    }
    tryPickup(a);

    // visuals
    const g = a.bean.group;
    g.position.x = a.x; g.position.z = a.z;
    g.rotation.y = a.yaw;
    const moving = Math.hypot(a.moveX, a.moveZ) > 0.12;
    a.walkT += dt * (moving ? 11 : 4);
    g.position.y = moving ? Math.abs(Math.sin(a.walkT)) * 0.24 : 0;
    const squish = moving ? 1 + Math.sin(a.walkT * 2) * 0.035 : 1;
    a.bean.body.scale.set(1 / squish * 1, 1.32 * squish, 0.92 / squish);
    a.bean.gun.position.z = lerp(a.bean.gun.position.z, 0.5, dt * 14);
    if (a.hitFlash > 0) {
      a.hitFlash -= dt;
      a.bean.body.material.emissive = new THREE.Color(0xff3344);
      a.bean.body.material.emissiveIntensity = 0.7;
    } else {
      a.bean.body.material.emissiveIntensity = 0;
    }
  }
}

/* ---------------- camera ---------------- */
function updateCamera(dt) {
  const tx = player.x + CAM_OFF.x, ty = CAM_OFF.y, tz = player.z + CAM_OFF.z;
  const k = 1 - Math.pow(0.0018, dt);
  camera.position.x = lerp(camera.position.x, tx, k);
  camera.position.y = lerp(camera.position.y, ty, k);
  camera.position.z = lerp(camera.position.z, tz, k);
  camera.lookAt(camera.position.x, 1.2, camera.position.z - CAM_OFF.z * 0.995);
}
camera.position.set(0, CAM_OFF.y, CAM_OFF.z + 60);
camera.lookAt(0, 0, 40);

/* ---------------- shop UI ---------------- */
function money(n) { return n === 0 ? 'FREE' : '🪙 ' + n; }
function renderShop() {
  $('gold-shop').textContent = meta.gold;
  $('gold-menu').textContent = meta.gold;
  const build = (gridId, items, selKey, renderCard) => {
    const grid = $(gridId);
    grid.innerHTML = '';
    for (const it of items) {
      const owned = meta.owned.includes(it.id);
      const sel = meta[selKey] === it.id;
      const card = document.createElement('div');
      card.className = 'card' + (sel ? ' sel' : '') + (owned ? '' : ' locked');
      card.innerHTML = renderCard(it) +
        `<div class="pr ${owned ? 'owned' : ''}">${sel ? '✓ EQUIPPED' : owned ? 'OWNED' : money(it.price)}</div>`;
      card.onclick = () => {
        audio();
        if (!meta.owned.includes(it.id)) {
          if (meta.gold < it.price) { card.animate([{ transform: 'translateX(0)' }, { transform: 'translateX(-5px)' }, { transform: 'translateX(5px)' }, { transform: 'translateX(0)' }], { duration: 200 }); return; }
          meta.gold -= it.price;
          meta.owned.push(it.id);
          sfx.pickup();
        }
        meta[selKey] = it.id;
        saveMeta();
        renderShop();
      };
      grid.appendChild(card);
    }
  };
  build('grid-weapons', SHOP_WEAPONS, 'spawnWeapon', it =>
    `<div class="em">${it.em}</div><div class="nm">${it.name}</div><div class="ds">${it.ds}</div>`);
  build('grid-colors', SHOP_COLORS, 'color', it =>
    `<div class="swatch" style="background:#${it.hex.toString(16).padStart(6, '0')}"></div><div class="ds"></div>`);
  build('grid-hats', SHOP_HATS, 'hat', it =>
    `<div class="em">${it.em}</div><div class="nm">${it.name}</div><div class="ds">${it.ds}</div>`);
}

/* ---------------- wire screens ---------------- */
$('btn-play').onclick = () => { audio(); startMatch(); };
$('btn-again').onclick = () => { audio(); startMatch(); };
$('btn-shop').onclick = () => { audio(); renderShop(); $('menu').classList.remove('on'); $('shop').classList.add('on'); };
$('btn-back').onclick = () => { audio(); $('shop').classList.remove('on'); $('menu').classList.add('on'); renderShop(); };
$('btn-menu').onclick = () => { audio(); $('results').classList.remove('on'); $('menu').classList.add('on'); renderShop(); };
$('mute').onclick = () => { muted = !muted; $('mute').textContent = muted ? '🔇' : '🔊'; };
renderShop();

/* ---------------- main loop ---------------- */
let last = performance.now();
let hudT = 0;
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min((now - last) / 1000, 0.05);
  last = now;

  if (match.state === 'playing' || match.state === 'over') {
    if (match.state === 'playing') {
      match.time += dt;
      readInput();
      updateZone(dt);
    }
    updateAgents(dt);
    updateBullets(dt);
    animateLoot(dt);
    updateCamera(dt);
    if (vignetteT > 0) { vignetteT -= dt; if (vignetteT <= 0) vignette.style.opacity = 0; }
    hudT -= dt;
    if (hudT <= 0 && player) { hudT = 0.12; updateHUD(); drawMinimap(); setZoneMsg(); }
  } else if (match.state === 'countdown') {
    updateAgents(0.0001);
    animateLoot(dt);
    updateCamera(dt);
  } else {
    // idle menu: slow orbit over the empty map
    const t = now / 1000;
    camera.position.set(Math.sin(t * 0.08) * 70, 42, Math.cos(t * 0.08) * 70);
    camera.lookAt(0, 0, 0);
    animateLoot(dt);
  }
  renderer.render(scene, camera);
}
spawnLoot();  // dress the menu backdrop
requestAnimationFrame(frame);

/* debug: ?autostart=1 skips the menu (used for automated testing) */
if (new URLSearchParams(location.search).get('autostart')) startMatch();
})();
