# BullpenLM iOS — TestFlight Runbook (v1.0.0)

The Apple Developer / App Store Connect steps Claude can't fly for you.
Everything else (Swift code, the Xcode project, build, version bumps)
lands automatically; this doc is the human-only path through the portal.

**What this app is:** a thin native shell (WKWebView) around the mobile
team-scorecard dashboard (`floor/app/team.html`). It opens to your
bullpen's roster → tap a rep → their scorecard. The shell adds a native
home, pull-to-refresh, a settings sheet (which bullpen / who you are),
and the mic entitlement for future voice drills.

- **Bundle id:** `com.beerslabs.bullpenlm`
- **Team:** `6APT8W6L8F` (**Beers Labs LLC** — the business entity, same as
  LootLens). Requires the LLC enrollment to be active and your Apple ID to have
  access to it. Xcode creates the iOS distribution cert + provisioning at first
  archive via automatic signing — no manual cert step.

---

## Pre-flight checklist (do once, ever)

- [ ] **Apple Developer Program membership active** for team `6APT8W6L8F` (Beers Labs LLC)
  — https://developer.apple.com/account
- [ ] **App Store Connect record exists** for `com.beerslabs.bullpenlm`
  — create at https://appstoreconnect.apple.com/apps (New App → iOS →
  pick the bundle id → name e.g. "Bullpen", SKU `bullpenlm-ios`)
- [ ] **TestFlight Beta App Information** filled (description, what to
  test, your email) — required once before adding testers
- [ ] **Apple Distribution certificate** in your login Keychain
  (Xcode → Settings → Accounts → Manage Certificates → "+" → Apple Distribution)
- [ ] **No third-party SDKs** → no Privacy Manifest required-reason
  entries needed beyond the mic usage string already in Info.plist

## Per-release flow

After Claude bumps the build number + commits:

### 1. Generate + open
```
cd ~/bullpenlm/ios
xcodegen generate
open BullpenLM.xcodeproj
```
In Xcode: BullpenLM target → General → Identity. Confirm Version `1.0.0`,
Build `1` (must be greater than the last TestFlight build — bump
`CFBundleVersion` in `project.yml` + re-`xcodegen generate` if needed).

### 2. Archive
Xcode menu: **Product → Destination → Any iOS Device (arm64)**,
then **Product → Archive**. Organizer opens when done.

### 3. Upload
In Organizer: select the archive → **Distribute App** →
**App Store Connect → Upload** → **Automatically manage signing** →
**Upload**. Apple processes it server-side (5–15 min); you get an email.

### 4. Push to TestFlight
App Store Connect → your app → **TestFlight** tab:
1. Wait for the build to finish "Processing"
2. Add it to a group (Internal first — you; then an External group)
3. Add testers by email: **Kelly**, **Will**, you
4. External testers need a one-time Beta App Review (usually < a day)
5. Testers get the invite → install **TestFlight** → tap your link → done

---

## SP3 — Push notifications (BUILT; needs your APNs key to deliver)

The full pipeline ships in the app + server already:
- iOS requests push, registers the APNs token to
  `POST /api/b/<bullpen>/push/register` (PushManager.swift + AppDelegate).
- Server stores tokens (`push.py`) and fires an alert when a
  notify-worthy audit event lands (`deal_closed_won`,
  `drill_passed_cert`, `gate_cleared`, `joined`, `w9_submitted`).
- Until the key is set it's a **logged no-op** (`[push] (no APNs key)
  would notify …`), so nothing breaks.

**To turn delivery on (one-time, your Apple steps):**

1. **App ID push capability** — developer.apple.com → Identifiers →
   `com.beerslabs.bullpenlm` → enable **Push Notifications**. Re-download
   / let Xcode refresh the provisioning profile.
2. **Create an APNs Auth Key** — developer.apple.com → Keys → "+" →
   **Apple Push Notifications service (APNs)** → download the `.p8`
   (only downloadable once). Note the **Key ID** and your **Team ID**.
3. **On the host**, put the `.p8` somewhere safe and set env vars for the
   server (in `~/Library/LaunchAgents/com.bullpenlm.server.plist` under
   `EnvironmentVariables`, then `launchctl bootout`/`bootstrap`):
   - `APNS_KEY_PATH` = /path/to/AuthKey_XXXX.p8
   - `APNS_KEY_ID` = the Key ID
   - `APNS_TEAM_ID` = your Team ID
   - `APNS_TOPIC` = com.beerslabs.bullpenlm
4. **Add the send deps + rebuild the sidecar** (one time):
   ```
   source ~/bullpenlm/.venv-build/bin/activate
   pip install "pyjwt[crypto]" "httpx[http2]"
   cd ~/bullpenlm/desktop/src-tauri/binaries
   pyinstaller --clean --noconfirm bullpenlm-server.spec
   cp dist/bullpenlm-server "../target/release/bundle/macos/BullpenLM.app/Contents/MacOS/bullpenlm-server"
   launchctl kickstart -k gui/$(id -u)/com.bullpenlm.server
   ```
   (TestFlight/App Store builds use the **production** APNs host; Xcode
   sets `aps-environment=production` on the distribution archive. Dev
   builds run on the sandbox host — the app sends `env=sandbox` in DEBUG.)

After that, an operator running the app gets a real push the moment a
rep on their bullpen closes / certifies / clears the gate.

## Later (not built)
- Native scorecard screens (if we outgrow the WKWebView).
- "Went stale" time-based nudges (needs a periodic checker, not just the
  event hook).
