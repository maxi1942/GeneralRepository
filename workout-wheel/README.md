# Workout Wheel 🎡

A workout logger for two. Log workouts (with an optional photo) to earn points, then spend points to spin a prize wheel.

- **Try it without any setup:** open `index.html?demo` (e.g. `…/workout-wheel/?demo`). Demo data is fake and resets on reload.
- **Cost:** £0. GitHub Pages hosts the app and the Supabase free tier holds the data. Neither needs a credit card.

## Points rules

All the numbers live in **`rules.js`** (the `RULES` block at the top). Change a number there and the whole app follows.
Points are never stored. They're recalculated from the logs every time, which is why the *Points* tab can show every point line by line.

| Rule | Points |
|---|---|
| Workout (max 1 per day counts) | +1 |
| Active week: 3+ workouts Mon–Sun | +1 |
| Monthly winner: most workouts in a calendar month (ties: both) | +1 |
| Spin the wheel | −12 |

Backdating up to 7 days is allowed and is always flagged in History. Deleted workouts lose their points but stay visible.

---

## One-time setup (about 20 minutes, no coding)

### Step 1: Create a free Supabase project
1. Go to **https://supabase.com** → **Start your project** → sign up (GitHub login is easiest).
2. Click **New project**.
   - Name: `workout-wheel`
   - Database password: click **Generate** (you won't need it again, but save it in your password manager)
   - Region: pick the one closest to you (e.g. *Central EU (Frankfurt)* or *North EU (Stockholm)*)
   - Plan: **Free**
3. Click **Create new project** and wait ~2 minutes.

### Step 2: Create the database tables
1. In the left sidebar, click **SQL Editor**.
2. Click **+ New query**.
3. Open [`supabase/schema.sql`](supabase/schema.sql) in this repo, copy **all** of it, and paste it in.
4. Click **Run** (bottom right). You should see *"Success. No rows returned"*.

### Step 3: Create your two logins
1. Left sidebar → **Authentication** → **Users** → **Add user** → **Create new user**.
2. Enter your email and a password. **Tick "Auto Confirm User"** → **Create user**.
3. Repeat for your wife.

### Step 4: Lock it down (important)
This stops strangers from creating accounts and seeing your data.
1. **Authentication** → **Sign In / Providers** (on some versions: **Providers** → **Email**).
2. Turn **off** "Allow new users to sign up" → **Save**.

### Step 5: Connect the app to your database
1. Left sidebar → **Project Settings** (gear icon) → **API** (may be called **Data API** / **API Keys**).
2. Copy the **Project URL** (looks like `https://abcdxyz.supabase.co`).
3. Copy the **anon public** key (may be labelled **publishable** key). **Do not** use the `service_role` / secret key.
4. On GitHub, open `workout-wheel/config.js` → click the ✏️ pencil → replace the two placeholder values → **Commit changes**.

> The anon key is designed to be public. Your data is protected by the security rules from Step 2 plus sign-ups being off (Step 4).

### Step 6: Publish
The app is served by GitHub Pages from the `main` branch (same as `squish-royale`). Once this folder is on `main`, it's live at:

**https://maxi1942.github.io/GeneralRepository/workout-wheel/**

(If the page 404s: GitHub repo → **Settings** → **Pages** → Source: *Deploy from a branch*, Branch: `main` / `(root)` → Save. Wait 1–2 minutes.)

### Step 7: Put it on your phones
- **iPhone:** open the link in **Safari** → Share button → **Add to Home Screen**.
- **Android:** open in **Chrome** → ⋮ menu → **Add to Home screen** / **Install app**.

Sign in. The first time, it asks for your name.

---

## Good to know
- **Supabase pauses free projects after 7 days with no activity.** If that happens (say, on holiday), log in at supabase.com and click **Restore project**. Nothing is lost.
- **Free limits:** 500 MB database and 1 GB of photo storage. Photos are shrunk to ~150–250 KB, so that's ~5,000 photos.
- **Tests** for the points maths: `cd workout-wheel && node --test`.
