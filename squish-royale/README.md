# Squish Royale — playable prototype

A mobile-first 3D battle royale prototype: 20 round "beans" drop into a shrinking
zone, loot weapons, and fight until one is left. Aim is horizontal-only (yaw) by
design — twin-stick friendly.

## Play it

Open `index.html` in any browser (no build step, no server needed).

- **Mobile:** left half of the screen = move stick, right half = aim stick
  (push past ~40% to fire).
- **Desktop:** WASD to move, mouse to aim, hold left button to fire.

## What's in the prototype

- You + 19 bots (simple state-machine AI: loot, engage, strafe, flee the zone)
- Shrinking zone in 6 phases with escalating damage; minimap shows current +
  next circle
- Loot: SMG / shotgun / rifle / railgun sniper, medkits, armor plates
  (auto-pickup, higher tier replaces lower)
- Gold economy: +25 per elimination plus placement bonus, persisted in
  `localStorage`
- Shop between matches: **sidegrade** spawn weapons (SMG / shotgun / rifle —
  different playstyles, not raw upgrades; sniper is loot-only), bean colors,
  and hats
- Tiny synth SFX (mutable), kill feed, damage vignette, victory / results flow

## Design intents

- Spawn loadouts are sidegrades so the battle-royale "everyone drops in equal"
  promise survives the meta-progression.
- The strongest gear (sniper, armor, meds) is field loot only.
- Characters are original: egg-shaped body, two eyes, antenna, little feet —
  bean-like, not crewmate-like.

## Files

- `index.html` — UI shell, screens, HUD, styles
- `game.js` — all game logic (Three.js scene, agents, AI, zone, loot, shop)
- `vendor/three.min.js` — Three.js r152 (vendored so the game runs offline)

## Not in scope (yet)

Real multiplayer (needs an authoritative server — Node/WebSocket or Colyseus),
accounts, teams/duos, matchmaking, anti-cheat.
