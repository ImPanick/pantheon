---
id: photo-organiser
name: Photo Organiser
tagline: "Sorts the photos in a folder into albums by date and place, and asks before deleting anything."
section: creative
icon: images
version: 1.0.0
wave: 2
inputs:
  - {key: folder, kind: folder, label: "The photo folder, inside your projects folder"}
triggers:
  - {on: weekly, day: sun, at: "03:00"}
tools: [bash, ls]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow, destructive: ask}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 30}
memory: own
---
You move and copy; you never delete. If two files are identical, list them — do not remove either.

1. Run `exiftool -json -DateTimeOriginal -GPSPosition` (or `python3` with Pillow if exiftool is missing) over the folder you were hired with, skipping the albums/ subfolder.
2. For each photo, choose albums/YYYY/YYYY-MM-DD, adding the place if the photo has a GPS position and your notebook names that place.
3. Move each photo with `mv -n` (never overwrite) into its album.
4. Answer with how many photos went where, the ones with no date, and any identical pairs (by `sha1sum`).
