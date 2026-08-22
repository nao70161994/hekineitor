# Mobile QA

## Result CTA

- Open a completed result on a narrow viewport.
- Confirm the primary share button is visible without hunting.
- Confirm share, retry, continue, feedback, and detail feedback controls are easy to tap.
- Confirm long fetish names do not overflow buttons or cards.

## Diagnosis Flow

- Start a new diagnosis.
- Answer at least five questions.
- Confirm progress messages are readable and do not push the main question off-screen.
- Confirm the adaptive phase text does not promise a fixed remaining question count.
- Use Back and confirm the previous question appears.
- Leave mid-diagnosis, reload, and confirm resume banner behavior.

## Feedback Flow

- Submit each quick feedback option: `当たってる`, `惜しい`, `違う`.
- Confirm the thank-you state appears and detail feedback remains optional.
- Open detail feedback and confirm item buttons are tappable.

## PWA

- On Android Chrome, confirm install prompt/banner behavior.
- On iOS Safari, confirm install guidance copy appears when applicable.
- After a service worker update, confirm update prompt reloads cleanly.

## Current Automation

- Flask/Vitest/Chromium cover result CTA markup, 48px target contracts, resume, feedback, manifest, service worker, offline, 320px overflow, 200%/400% text enlargement, axe, keyboard dialog, and visual baselines.
- Native share sheet, OS install prompt, installed-PWA lifecycle, and physical-device screen-reader behavior remain manual QA items.

## Execution Log

See [`QA.md`](QA.md) for the current automation boundary and manual checklist. Record dated device/browser results in the PR or release record.
