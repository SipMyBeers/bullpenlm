# App Store — App Privacy declarations (BullpenLM iOS)

What to enter in App Store Connect → your app → **App Privacy**. BullpenLM is
operator-hosted (each team's data lives on its own server; no central BullpenLM
database), which keeps the footprint small. Privacy policy URL:
**https://bullpenlm.com/privacy**

## Does this app collect data? → YES (a small amount)

| Data type | Collected | Linked to user | Used for tracking | Purpose |
|---|---|---|---|---|
| **Name** (rep/operator handle you enter) | Yes | Yes | **No** | App Functionality |
| **Device ID** (APNs push token, only if notifications enabled) | Yes | Yes | **No** | App Functionality |

- **Used for Tracking: NO** for everything. The app does no cross-app/advertising
  tracking and contains no ad/analytics SDKs.
- Everything is **App Functionality** only (render scorecards; deliver your team's
  push notifications via Apple APNs).
- Training/performance activity (drills, deals, ranks) is generated and stored on the
  operator's own server, not collected into a BullpenLM-controlled dataset — so it is
  not declared as data *we* collect. The only identity datum the app sends is the
  name/handle the user types and (optionally) the push token.

## Notes for the reviewer / Beta App Information
- A cold open shows a **read-only demo team** (fictional sample data) so the app is
  fully functional without an account — no login wall (Guideline 4.2 / 5.1.1 safe).
- To connect a real team: tap the demo bar or the gear, enter a bullpen slug.
- Notifications are requested only after a real bullpen is connected, not on the demo.

## If asked about account deletion (Guideline 5.1.1(v))
Operator-hosted: a user's data lives on their operator's server and is removed there.
The app stores only local settings (cleared on uninstall). Deletion/questions:
dylan@ranger-beers.com.
