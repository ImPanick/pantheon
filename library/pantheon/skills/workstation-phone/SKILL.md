---
name: workstation-phone
description: Use the person's generic Android device, with a selected hardware profile, through the computer tool (screen phone) and adb to test an app or mobile website.
version: 1.2.0
category: workstation
tags: [workstation, phone, android, mobile, emulator, pixel, galaxy, samsung, fold, tablet, app, apk, adb, touch, responsive]
requires_toolsets: [computer, bash]
status: published
confidence: 0.85
source: pantheon
---

## When to Use

Anything on a phone: how a site looks and works on a phone, an Android app (install, run, read its log), a foldable's display regions. Android runs in the person's own VM with a generic OS and the selected hardware profile; it does not provide OEM firmware or retail identity. Its first use turns it on only when its actual prerequisites are met.

## Procedure

1. `computer` with `"screen": "phone"` and action `screenshot`. Booting? `wait` (ms) and look again; the first boot takes a minute or two.
2. Touch by mark or by the screenshot's own pixels (its size is stated with it): `click` taps, `drag` swipes (x,y to to_x,to_y), `scroll` flings, `type` enters text into the focused field, `key` `Return` submits. `right_click` is Back, `middle_click` Home.
3. adb in `bash` reaches this phone already (`ANDROID_SERIAL` is set): `adb shell am start -a android.intent.action.VIEW -d 'https://…'` opens a page in Chrome; `adb install -r app.apk`; `adb logcat -d | tail -200` reads the log; `adb shell input keyevent 26` power, `24`/`25` volume; `adb emu fold` / `adb emu unfold` a foldable; `adb emu rotate` turns it.
4. A site served in the workstation is at `http://10.0.2.2:<port>` from the phone (the emulator's address for its host).
5. Drive it as the person does, with the phone's own controls (each returns a screenshot after it): `press` with `button` (power, volume_up, volume_down, back, home, recents), `rotate`, `fold` / `unfold` a foldable, `open_url` with `url`.
6. Another device: `use_device` with `device` (such as galaxy_z_fold6), as the person picks it in the Devices room. One not on the workstation yet is installed first, which takes minutes; the result says so — `wait` and take a `screenshot` until it is on. If it says the Android SDK License must be accepted, ask the person to accept it in the Workbench's Devices room; you cannot accept it for them.
7. Look at every result before the next step, and say what the last screenshot shows.

## Pitfalls

- Typing before a field is tapped sends nothing useful; tap it first.
- "Busy" means a person holds the screens: ask them, or wait. Do not retry in a loop.
- Unavailable says why (no KVM, cannot install): tell the person that sentence.
- Android requires host KVM and usable KVM inside that user's VM. A shared workstation, separate ADB ports, or a guest KVM node under software emulation is insufficient. Do not change backend/security settings, accept SDK terms, migrate device data, or substitute a browser to work around a refusal.
- Google Play is an optional separately licensed developer image, selected and accepted by a person. Sign-in happens on Android itself; the user's agents share that device and can see its sessions. Never claim sign-in, Play Integrity or a retail device is verified from a browser preview.
- The person's USB tether control sends selected uploads or owned document text into Android Downloads. It is file transfer, not a host mount or network tether; do not promise binary originals from the document-text export.
- A mobile view (the screenshot says so) is a phone-shaped Firefox, not Android: web pages only, no adb, no apps, no marks. Back and Home are the phone action's buttons; scroll moves the page. Say it is a mobile view when you report what a site looks like.
