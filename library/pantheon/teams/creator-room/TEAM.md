---
id: creator-room
name: Creator Room
tagline: "Content made for social: the research, the posts, threads, carousels, video scripts, the visuals and their captions, voice-checked."
members: [hook-and-hashtag-researcher, post-writer, thread-writer, carousel-writer, short-video-scripter, visual-creator, caption-writer, brand-voice-keeper, social-media-manager]
flow:
  - {from: hook-and-hashtag-researcher, to: post-writer, via: "document:Hooks and hashtags"}
  - {from: hook-and-hashtag-researcher, to: thread-writer, via: "document:Hooks and hashtags"}
  - {from: hook-and-hashtag-researcher, to: carousel-writer, via: "document:Hooks and hashtags"}
  - {from: hook-and-hashtag-researcher, to: short-video-scripter, via: "document:Hooks and hashtags"}
  - {from: post-writer, to: visual-creator, via: "document:Posts"}
  - {from: carousel-writer, to: visual-creator, via: "document:Carousel"}
  - {from: visual-creator, to: caption-writer, via: "document:Visuals"}
  - {from: post-writer, to: brand-voice-keeper, via: "document:Posts"}
  - {from: thread-writer, to: brand-voice-keeper, via: "document:Thread"}
  - {from: short-video-scripter, to: brand-voice-keeper, via: "document:Video script"}
  - {from: caption-writer, to: brand-voice-keeper, via: "document:Captions"}
  - {from: brand-voice-keeper, to: social-media-manager, via: "document:Voice review"}
---
Each member is its own hire with its own settings and reports. The room makes the content; the Social Desk runs the week. Every member drafts and nothing is posted until a social connector lands. The Visual Creator needs image generation turned on in Settings to make pictures; without it, it writes each image as a brief a designer can work from.
