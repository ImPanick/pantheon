---
id: social-desk
name: Social Desk
tagline: "The week's social, staffed: the trends, the calendar, the drafts, the voice check, the replies, the listening, the launch and the numbers."
members: [trend-spotter, content-calendar, social-media-manager, brand-voice-keeper, community-manager, social-listener, launch-announcer, social-analytics-reporter, influencer-scout, repurposer]
flow:
  - {from: content-calendar, to: social-media-manager, via: "document:Content calendar"}
  - {from: repurposer, to: social-media-manager, via: "document:Repurposed"}
  - {from: launch-announcer, to: social-media-manager, via: "document:Launch announcement"}
  - {from: social-media-manager, to: brand-voice-keeper, via: "document:Social drafts"}
  - {from: brand-voice-keeper, to: social-media-manager, via: "document:Voice review"}
  - {from: social-media-manager, to: community-manager, via: "document:Social drafts"}
  - {from: social-listener, to: community-manager, via: "document:Social listening"}
  - {from: social-analytics-reporter, to: social-media-manager, via: "document:Social performance"}
  - {from: trend-spotter, to: content-calendar, via: "event:report_filed"}
  - {from: influencer-scout, to: community-manager, via: "document:Creator shortlist"}
---
Each member is its own hire with its own settings and reports. The flow says who hands to whom — by the document each writes, or by the report it files — and the hall draws it; today the person opens the next member with that document, and the day delegation lands (the plan's D4) *Hire all* compiles the flow into triggers. Posting itself is not in the desk: every member drafts, and the person posts, until a social connector lands.
