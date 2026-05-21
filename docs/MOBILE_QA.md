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

- Flask smoke covers result CTA markup, resume API, feedback API, manifest, service worker, and offline routes.
- Real tap target size, native share sheet, and install prompt behavior remain manual QA items.
