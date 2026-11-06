# Publishing Author's Hand on the Google Play Store

Author's Hand is a web app (Streamlit). The Play Store version is a thin Android shell (Capacitor) that opens your deployed app full-screen, so every update you deploy reaches phone users instantly — no app update needed.

## Step 1 — Deploy the web app (once)
**Option A — Streamlit Community Cloud (free)**
1. Create a GitHub account → **New repository** → upload the contents of `Final_Capstone_Project`.
2. Go to **share.streamlit.io** → **Create app** → choose the repository, branch `main`, file `app.py` → **Deploy**.
3. (Optional) **App settings → Secrets**: add `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `CONTACT_EMAIL` etc.
4. Copy the URL, e.g. `https://authorshand.streamlit.app`.
5. (Optional) To switch on **Continue with Google / ORCID** online, paste this into **Secrets** (redirect URI must be
   your https address + `/oauth2callback`, registered the same way in Google Cloud and ORCID Developer Tools):
   ```toml
   [auth]
   redirect_uri = "https://authorshand.streamlit.app/oauth2callback"
   cookie_secret = "any-long-random-text"
   [auth.google]
   client_id = "…apps.googleusercontent.com"
   client_secret = "…"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   [auth.orcid]
   client_id = "APP-…"
   client_secret = "…"
   server_metadata_url = "https://orcid.org/.well-known/openid-configuration"
   ```

> Community Cloud storage is temporary. For a permanent multi-user workspace use Option B with a persistent disk mounted at `/data`.

**Option B — Docker host (Render / Railway / Cloud Run / Azure)**
1. Point the host at the repository; it detects the `Dockerfile`.
2. Add a persistent disk mounted at `/data` (the workspace database lives there).
3. Copy the public URL.

> **Sign-in inside the phone app.** E-mail/Gmail + password and ORCID iD + password work everywhere.
> Google blocks its own sign-in page inside app WebViews (error *disallowed_useragent*), so in the Play Store
> build use e-mail/password or **Continue with ORCID**; *Continue with Google* works in the browser / home-screen
> version (Step 2) and the Windows app.

## Step 2 — Quick “install” without the store
On Android Chrome or iPhone Safari open the URL → menu → **Add to Home screen**. Done.

## Step 3 — Build the Play Store app
1. Install **Node.js LTS** and **Android Studio** (with an SDK and the default emulator).
2. Open a terminal in the `mobile` folder.
3. Edit `capacitor.config.json` → replace `https://YOUR-APP.streamlit.app` with your URL (also in `www/index.html`).
4. Run:
   ```
   npm install
   npx cap add android
   npx cap sync android
   npx cap open android
   ```
5. In Android Studio: **app → res → mipmap** → right-click → **New → Image Asset** → add your icon.
6. Test: press ▶ **Run** (emulator or a phone with USB debugging).
7. Build the store bundle: **Build → Generate Signed App Bundle / APK → Android App Bundle** → create a new keystore (keep it safe — you need it for every update) → **release** → **Create**. You get `app-release.aab`.

## Step 4 — Publish in Google Play Console
1. Open **play.google.com/console** → pay the one-time US$25 developer registration → verify identity.
2. **Create app** → name *Author's Hand*, type *App*, *Free*.
3. **Dashboard → Set up your app**: privacy policy URL, app access (explain the demo e-mail `demo@authorshand.app`), ads (*No*), content rating questionnaire, target audience (*18+*), data safety form (the app stores the e-mail and research library you enter).
4. **Main store listing**: short & full description, 512×512 icon, 1024×500 feature graphic, at least 2 phone screenshots (use the images in `screenshots/v3`).
5. **Testing → Closed testing** (new personal accounts must run a closed test with at least 12 testers for 14 days) → upload `app-release.aab`.
6. After the test period: **Production → Create new release** → upload the same bundle → **Review release → Start roll-out**.

## Step 5 — iPhone (optional)
`npx cap add ios` on a Mac with Xcode, then submit through App Store Connect (Apple Developer Program, US$99/year).
