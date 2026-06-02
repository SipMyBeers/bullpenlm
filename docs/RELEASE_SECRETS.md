# Release secrets — what to populate before the alpha goes out

Both the **local notarized build** (`desktop/scripts/build-notarized.sh`) and the
**CI release workflow** (`.github/workflows/release.yml`) need Apple Developer
creds. Local builds use a gitignored env file on disk. CI uses GitHub repo
secrets. Same logical creds, two delivery mechanisms.

Beers Labs LLC has only one Mac signing identity in the keychain right now —
`Developer ID Application: Dylan Beers (NV5993W4T4)` — and `tauri.conf.json`
already references it by name. So codesigning works today. What's missing
is notarization: Apple wants to call back to your account to verify the
build before letting Gatekeeper accept it on a fresh Mac.

---

## What you need to generate once

### 1. App-specific password (for `APPLE_PASSWORD`)

Apple's notary service won't accept your regular Apple ID password.
Generate a dedicated one:

1. Sign in at https://account.apple.com/account/manage
2. Sign-In and Security → **App-Specific Passwords** → Generate Password
3. Label it `BullpenLM notarization`
4. Save the result (`xxxx-xxxx-xxxx-xxxx`) in your password manager — Apple
   only shows it once

### 2. Team ID (for `APPLE_TEAM_ID`)

For Beers Labs LLC this is `NV5993W4T4`. Verify at
https://developer.apple.com/account → Membership → Team ID.

### 3. (CI only) Exported `.p12` certificate

CI runners don't have your keychain — they need the cert as a base64-encoded
`.p12`. From your Mac:

```bash
# 1. Export the cert from Keychain Access → "Developer ID Application: …"
#    Right-click → Export → save as developer-id.p12 with a strong password
# 2. Base64-encode it
base64 -i developer-id.p12 -o developer-id.p12.b64
# 3. Copy the resulting one-line value into the APPLE_CERTIFICATE secret
```

---

## Local build (your Mac, hand-distributed builds)

```bash
cp desktop/.env.notarize.example desktop/.env.notarize
$EDITOR desktop/.env.notarize        # fill in the three values
bash desktop/scripts/build-notarized.sh
```

`build-notarized.sh` rebuilds the PyInstaller sidecar, then runs
`cargo tauri build` with the notarization env vars present so the bundler
submits to Apple and staples the result. Expect ~3 min wall-clock — most
of that is waiting on Apple. The script ends by running
`xcrun stapler validate` and `spctl -a -vv` so you can confirm Gatekeeper
will accept the build on a fresh Mac.

The output you want to give friends:

```
desktop/src-tauri/target/release/bundle/dmg/BullpenLM_0.1.0_aarch64.dmg
```

Once this build is stapled, **you can hand it to anyone on macOS** and it
will open with no warning.

---

## CI build (GitHub Releases)

Set these as **repo secrets** at
https://github.com/SipMyBeers/bullpenlm/settings/secrets/actions:

| Secret name                  | Value                                          |
| ---------------------------- | ---------------------------------------------- |
| `APPLE_CERTIFICATE`          | base64-encoded `.p12` contents (one line)      |
| `APPLE_CERTIFICATE_PASSWORD` | the password you used when exporting the `.p12`|
| `APPLE_ID`                   | your Apple Developer email                     |
| `APPLE_PASSWORD`             | the app-specific password from step 1 above    |
| `APPLE_TEAM_ID`              | `NV5993W4T4`                                   |

Or with the `gh` CLI:

```bash
gh secret set APPLE_CERTIFICATE          < developer-id.p12.b64
gh secret set APPLE_CERTIFICATE_PASSWORD                          # interactive prompt
gh secret set APPLE_ID          --body "you@example.com"
gh secret set APPLE_PASSWORD    --body "xxxx-xxxx-xxxx-xxxx"
gh secret set APPLE_TEAM_ID     --body "NV5993W4T4"
```

Tagging a release then auto-builds + notarizes all four platforms:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

A draft release shows up on GitHub with the stapled `.dmg`, `.exe`, and
`.AppImage` attached. Review, publish.

---

## Windows codesigning (later — not blocking the alpha)

`WIN_CSC_LINK` (base64 `.pfx`) + `WIN_CSC_KEY_PASSWORD` enable Authenticode
signing for Windows builds. SmartScreen will still warn until the cert is
"warmed up" by enough downloads. Punt until friends-and-family Mac alpha is
out the door.
