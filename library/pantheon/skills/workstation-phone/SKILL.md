---
name: workstation-phone
description: Use the person's phone — a real Android device such as a Pixel or a Galaxy — with the computer tool (screen phone) and adb, to test an app or how a website works on a phone.
version: 1.0.0
category: workstation
tags: [workstation, phone, android, mobile, emulator, pixel, galaxy, samsung, fold, tablet, app, apk, adb, touch, responsive]
requires_toolsets: [computer, bash]
status: published
confidence: 0.85
source: pantheon
---

## When to Use

Anything on a phone: how a site looks and works on a phone, an Android app (install, run, read its log), a foldable's two screens. The phone is Google's Android Emulator in the workstation, as the device the person chose (Pixel, Galaxy, Fold, tablet); its first use turns it on.

## Procedure

1. `computer` with `"screen": "phone"` and action `screenshot`. Booting? `wait` (ms) and look again; the first boot takes a minute or two.
2. Touch by mark or by the screenshot's own pixels (its size is stated with it): `click` taps, `drag` swipes (x,y to to_x,to_y), `scroll` flings, `type` enters text into the focused field, `key` `Return` submits. `right_click` is Back, `middle_click` Home.
3. adb in `bash` reaches this phone already (`ANDROID_SERIAL` is set): `adb shell am start -a android.intent.action.VIEW -d 'https://…'` opens a page in Chrome; `adb install -r app.apk`; `adb logcat -d | tail -200` reads the log; `adb shell input keyevent 26` power, `24`/`25` volume; `adb emu fold` / `adb emu unfold` a foldable; `adb emu rotate` turns it.
4. A site served in the workstation is at `http://10.0.2.2:<port>` from the phone (the emulator's address for its host).
5. Look at every result before the next step, and say what the last screenshot shows.

## Pitfalls

- Typing before a field is tapped sends nothing useful; tap it first.
- "Busy" means a person holds the screens: ask them, or wait. Do not retry in a loop.
- Unavailable says why (built without the phone, no KVM): tell the person that sentence.
- A mobile view (the screenshot says so) is a phone-shaped Firefox, not Android: web pages only, no adb, no apps, no marks. Back and Home are the phone action's buttons; scroll moves the page. Say it is a mobile view when you report what a site looks like.
