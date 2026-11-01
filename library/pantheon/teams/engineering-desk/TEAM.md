---
id: engineering-desk
name: Engineering Desk
tagline: "A change from idea to release: the design, the API, the security read, the test plan, the nightly triage, the change window and the notes."
members: [architect, api-designer, security-reviewer, test-planner, regression-triager, change-manager, release-notes-owner]
flow:
  - {from: architect, to: api-designer, via: "document:Design"}
  - {from: architect, to: security-reviewer, via: "document:Design"}
  - {from: api-designer, to: test-planner, via: "document:API design"}
  - {from: test-planner, to: regression-triager, via: "document:Test plan"}
  - {from: regression-triager, to: release-notes-owner, via: "document:Test triage"}
  - {from: change-manager, to: release-notes-owner, via: "document:Change record"}
  - {from: security-reviewer, to: release-notes-owner, via: "event:report_filed"}
---
Each member is its own hire with its own settings and reports. The flow says who hands to whom — by the document each writes, or by the report it files — and the hall draws it; today the person opens the next member with that document, and the day delegation lands (the plan's D4) *Hire all* compiles the flow into triggers.
