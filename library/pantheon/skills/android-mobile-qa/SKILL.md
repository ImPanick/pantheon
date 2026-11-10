---
name: android-mobile-qa
description: Test Android app or mobile-web behavior across phone, tablet and foldable profiles, including flip-phone rotation, folding and file-picker flows.
version: 1.0.0
category: mobile
tags: [android, mobile, qa, test, phone, tablet, foldable, flip, responsive, rotation, files]
requires_toolsets: [computer]
status: published
confidence: 0.9
source: pantheon
---

## When to Use

Use when the user asks for Android app QA, mobile website testing, responsive layouts, rotation, or fold/flip phone behavior.

## Procedure

- Load `workstation-phone` before driving Android. Establish the requested app/site, current profile and visible starting state with a phone screenshot. Use an already installed app or a reachable development URL; do not claim APK installation or workstation localhost routing is automatic.
- Pick a small matrix relevant to the change: ordinary portrait phone, landscape, tablet when supported, and a foldable or flip phone when requested. `use_device` changes profile; `rotate`, `fold` and `unfold` exercise supported transitions. Switching profiles may restart Android and show separate saved data. Preserve the user's initial profile for restoration when practical.
- On each state, inspect clipping, system insets, touch target placement, scrolling, keyboard overlap, dialogs, navigation and state retention. After rotation/folding use a fresh screenshot and fresh marks. The cover display can have different dimensions. Do not touch using coordinates from the unfolded screen.
- For file-picking or screenshot import, load `android-usb-files` when shell tools are available. Confirm `usb_status` reports the file synced before testing the Android picker. An upload queued in Pantheon is not evidence that the app received the file.
- Record expected behavior, observed behavior, reproduction steps and the affected profile/posture. Attach returned screenshots when useful. Restore the starting orientation/profile if the test changed them and the task does not ask to leave the test state.

## Pitfalls

Profiles emulate display geometry on generic Android, not OEM firmware. Folded-cover geometry does not prove a retail flip phone's secondary-screen APIs, hinge sensors or physical performance. Explicitly separate emulator results from untested real-hardware behavior. Do not change SDK images, accept licenses, reset data, install apps or sign in unless the task authorizes those steps.

## Verification

For each tested profile/posture, report the observed result and reproduction steps for failures. Fresh screenshots must show the claimed layout or interaction result; list real-device behaviors that remain untested.
