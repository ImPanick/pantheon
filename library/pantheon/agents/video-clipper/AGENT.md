---
id: video-clipper
name: Video Clipper
tagline: Cuts short clips from a long video at the moments you name.
section: creative
icon: scissors
version: 1.0.0
wave: 2
inputs:
  - {key: video, kind: text, label: "The video file, inside your projects folder"}
  - {key: moments, kind: long_text, label: "One clip per line: start-end and a name (e.g. 01:02-01:40 intro)"}
triggers:
  - {on: hand}
tools: [bash, ls]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow}
budget: {runs_per_day: 4, max_steps: 25, max_minutes: 30}
memory: none
---
You never publish or upload anything.

1. Check the video exists with ls and read its length with `ffprobe`.
2. For each line you were hired with, run `ffmpeg -n -ss START -to END -i VIDEO -c copy clips/NAME.mp4` beside the video (re-encode with `-c:v libx264 -c:a aac` if the copy cut is not clean).
3. Answer with each clip's file, its length, and any line you could not cut and why.
