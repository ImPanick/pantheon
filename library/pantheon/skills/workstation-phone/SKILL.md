---
name: workstation-phone
description: Operate the user's Android phone with the computer tool, inspect its screen, tap and type, rotate or fold it, and choose a device profile.
version: 2.0.0
category: workstation
tags: [workstation, phone, android, mobile, emulator, pixel, galaxy, samsung, fold, flip, tablet, touch]
requires_toolsets: [computer]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Use when the user asks you to operate an Android phone, tap or type in a mobile app, change orientation or exercise a foldable.

## Procedure

1. Start with `computer` action `screenshot`, `screen: phone`. This uses the selected Android VM and can start it if it is off. If it is booting, use `wait` with `ms` on `screen: phone`, then inspect again. Report a missing image, license or runtime prerequisite as returned; a person accepts SDK terms and chooses the image in the phone panel.
2. Use marks from the latest phone screenshot, or that screenshot's own pixel coordinates. `click` taps; `drag` swipes from x,y to to_x,to_y; `scroll` flings; `type` enters text after focusing a field. `key` with `Return` submits. `right_click` is Back and `middle_click` is Home. Never reuse desktop marks on the phone.
3. `press` with `button: back|home|recents|power|volume_up|volume_down` uses Android's controls. `rotate` turns the display a quarter. `fold` and `unfold` change a supported foldable's posture; inspect the new screenshot before touching it. `open_url` with `url` opens Android's browser when the task calls for it.
4. Use `use_device` with an ID from the computer schema, such as `galaxy_z_flip6`, only when the task calls for a different profile. It can stop the current phone and start/install the selected profile. Images and device profiles have separate saved data; do not promise files follow a switch.
5. `usb_status` reports the connected folder and per-file delivery state. `usb_connect` and `usb_eject` control shared storage without returning a screenshot. For file workflows load `android-usb-files`; for device/layout testing load `android-mobile-qa` through `use_skill` or `manage_skills action=view`.

## Pitfalls

- The dedicated Android worker may run on macOS, Windows or Linux, separately from the workstation. Workstation `bash` and its ADB do not automatically reach it. Do not start a second emulator, search for private ADB keys, or assume `10.0.2.2` points to the workstation. Use a reachable URL supplied by the deployment for development servers.
- There is no agent APK-install/logcat API in this tool. Sharing an APK file is not installing it; installing through Android UI requires the task's authorization. Do not invent shell access to the Android host.
- If a person holds the phone, stop input and ask them to hand it back. A transient busy operation can be checked once after waiting; do not repeatedly submit mutations.
- A browser preview is web-only, not Android. Hardware profiles use a generic Android OS, not Samsung/Pixel OEM firmware; emulator checks do not establish retail-device compatibility or Play Integrity.
## Verification

Inspect every returned picture. Report what actually worked and any untested device/OS behavior.
