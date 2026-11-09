# Workout Wheel 🎡

A workout logger for two. Log workouts (with an optional photo) to earn points, then spend points to spin a prize wheel.

- **Database:** a Google Sheet in your own Google account. Photos go into a Google Drive folder.
- **App:** a web page hosted free on GitHub Pages. Add it to your phone's home screen and it works like an app.
- **Cost:** £0. No extra accounts.
- **Try it without any setup:** add `?demo` to the address (e.g. `…/workout-wheel/?demo`). Demo data is fake and resets on reload.

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

## One-time setup (about 15 minutes, no coding)

Use a computer for this (not your phone), signed in to **your personal Google account**.

### Step 1: Create the Google Sheet
1. Go to **https://sheets.new**. A blank spreadsheet opens.
2. Click **"Untitled spreadsheet"** (top left) and rename it **Workout Wheel**.

### Step 2: Paste in the backend script
1. In the sheet's menu: **Extensions → Apps Script**. A new tab opens with a file called `Code.gs` containing a few lines of code.
2. **Select everything in that file and delete it** (Ctrl+A / Cmd+A, then Delete).
3. Open [`google-sheets/Code.gs`](google-sheets/Code.gs) on GitHub and click the **copy icon** (two squares, top right of the file).
4. Paste it into the empty Apps Script file.
5. Click the **💾 Save** icon. (Optional: rename the project at the top from "Untitled project" to **Workout Wheel**.)

### Step 3: Run the one-time setup
1. In the toolbar, there's a dropdown next to **▶ Run** and **Debug**. Make sure it says **`setup`**.
2. Click **▶ Run**.
3. A popup says *"Authorization required"*. Click **Review permissions** and choose your Google account.
4. You'll see **"Google hasn't verified this app"**. This is normal: it's your own script, not someone else's app.
   Click **Advanced** → **Go to Workout Wheel (unsafe)** → **Allow**.
   - It asks for **Sheets** access (to store the data) and **Drive** access (to save workout photos into a folder).
5. At the bottom, the log should end with **"✅ Setup done"**.

Go back to the spreadsheet tab. You'll now see 4 tabs at the bottom: **Players, Workouts, Prizes, Spins**, plus a new **"Workout Wheel photos"** folder in your Google Drive.

### Step 4: Set your names and passcodes
1. Open the **Players** tab.
2. Change the names in column B (`Max`, `Partner`) to your real names.
3. Change the passcodes in column C to **your own personal passcodes**. Each of you gets one, and it decides who you're logged in as.
   - Use something **not guessable**, like 3 random words: `purple-lamp-otter`. Avoid 4-digit numbers.
   - You each type yours **once per phone**, and the app remembers it.

**Don't edit anything else in the sheet by hand** (no renaming tabs or column headers, and no deleting rows). Reading it is fine. Use the app to change things.

### Step 5: Publish the backend
1. Back in the **Apps Script** tab, click the blue **Deploy** button (top right) → **New deployment**.
2. Click the **⚙️ gear** next to "Select type" → choose **Web app**.
3. Fill in:
   - Description: `Workout Wheel`
   - **Execute as: Me**
   - **Who has access: Anyone** (this is needed for the phones to reach it; the passcodes protect it)
4. Click **Deploy**. If asked to authorize again, repeat the "Advanced → Go to… → Allow" steps.
5. Copy the **Web app URL**. It looks like `https://script.google.com/macros/s/AKfy…/exec`.
6. Check it works: paste that URL into a new browser tab. You should see **"✅ Workout Wheel backend is running."**

### Step 6: Connect the app
Put the Web app URL into `workout-wheel/config.js` (or just send it to Claude to do it):
on GitHub, open the file → click the ✏️ pencil → replace `PASTE-YOUR-WEB-APP-URL-HERE` → **Commit changes**.

> The URL being public in the code is fine. Nothing can be read or written without a passcode.

### Step 7: Go live and put it on your phones
Once this folder is merged into `main`, the app lives at:

**https://maxi1942.github.io/GeneralRepository/workout-wheel/**

- **iPhone:** open the link in **Safari** → Share button → **Add to Home Screen**.
- **Android:** open in **Chrome** → ⋮ menu → **Add to Home screen**.

Open it and enter your passcode. Done.

---

## Good to know
- **Speed:** each save takes 1–3 seconds (that's Google Apps Script). Normal.
- **Photos** are saved to the "Workout Wheel photos" Drive folder and set to "anyone with the link can view", so the app can show them. The links are long random codes nobody can guess, but don't log anything you'd never want seen.
- **Changed `Code.gs` later?** Paste the new version, save, then **Deploy → Manage deployments → ✏️ → Version: New version → Deploy**. The URL stays the same.
- **Someone forgot their passcode?** Look it up in the Players tab.
- **Free limits:** far beyond what two people will ever use.
- **Tests:** `cd workout-wheel && node --test`. These cover the points maths and the backend script, run against a fake Google.
