---
name: android-usb-files
description: Share files between Android, the user's Pantheon projects and the workstation; inspect USB delivery status and diagnose a missing upload.
version: 1.0.0
category: mobile
tags: [android, usb, sharing, upload, download, screenshot, files, phone, transfer]
requires_toolsets: [computer, bash]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Use when the user wants a file on their phone, a screenshot is missing after upload, or Android and workstation files need to be shared.

## Procedure

1. Call `computer` action `usb_status`. Read `connected`, `folder`, `android_folder`, `workstation_connected`, `error` and the per-file `synced` flags. This observation does not boot Android. If needed, inspect `screen: phone` with `screenshot`, wait for boot, then use `usb_connect`. Respect a person's takeover; do not seize control.
2. The returned `folder` is relative to this user's Pantheon projects. In workstation `bash`, the same folder is under `$PANTHEON_PROJECTS`; quote both the variable and the returned relative path. Example for an actually returned folder: `ls -l -- "$PANTHEON_PROJECTS/Android USB/galaxy_s25_ultra-google_play"`. Never hard-code an owner directory or assume a path on the physical host is shared.
3. Copy only the requested files into that folder using workstation tools when `workstation_connected` is true. Use a new filename or inspect the existing file before replacing it. Android uses `Download/PantheonUSB`, accessible in its Files app. A document-text export contains text, not necessarily the original document binary.
4. Poll `usb_status` after allowing a sync interval (five seconds). `synced: true` means the last sync confirmed matching content; a local upload acceptance or a connected cable alone does not prove delivery. On an error, report the file as queued and the exact reason. Retry a transient busy observation once, then stop with the outstanding state if it persists.
5. Inspect the file on Android when visibility matters: `computer` with `screen: phone`, then navigate Files → Downloads → PantheonUSB. Image apps may need their local-device folder view or a refresh. Do not sign into a cloud service just to view a local file.
6. Eject with `usb_eject` only when requested or the task requires disconnecting. Check all requested files are synced first. Ejecting keeps both copies and stops future synchronization; switching profile/image requires a new connection.

## Pitfalls

The bridge is a flat folder, not a physical USB mount or network tether. It supports up to 64 files, 20 MB each, 128 MiB total; subfolders are not synced. Use ASCII letters/numbers, spaces, dots, underscores, hyphens and parentheses; no path separators, reserved device names or names differing only in case. Concurrent changes keep a conflict copy. Deletions stay local; do not promise deletion propagates.

## Verification

Finish with the exact destination, confirmed file names and delivery status. Distinguish queued bytes, verified shared files, and an image visibly opened on Android.
