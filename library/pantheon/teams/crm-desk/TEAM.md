---
id: crm-desk
name: CRM Desk
tagline: "The customer side of sales, kept current: calls written up, deals logged, leads triaged, quiet deals nudged, accounts mapped and planned."
members: [pipeline-keeper, contact-keeper, renewal-manager, call-summariser, deal-logger, lead-triager, quiet-deal-chaser, stakeholder-mapper, account-planner, win-loss-reviewer, crm-hygienist]
flow:
  - {from: call-summariser, to: deal-logger, via: "document:Call summary"}
  - {from: call-summariser, to: stakeholder-mapper, via: "document:Call summary"}
  - {from: deal-logger, to: pipeline-keeper, via: "document:Deal notes"}
  - {from: deal-logger, to: stakeholder-mapper, via: "document:Deal notes"}
  - {from: deal-logger, to: win-loss-reviewer, via: "document:Deal notes"}
  - {from: quiet-deal-chaser, to: pipeline-keeper, via: "document:Quiet deals"}
  - {from: stakeholder-mapper, to: account-planner, via: "document:Stakeholder map"}
  - {from: pipeline-keeper, to: account-planner, via: "document:Pipeline"}
  - {from: pipeline-keeper, to: renewal-manager, via: "document:Pipeline"}
  - {from: crm-hygienist, to: contact-keeper, via: "document:CRM hygiene"}
  - {from: crm-hygienist, to: pipeline-keeper, via: "document:CRM hygiene"}
---
Each member is its own hire with its own settings and reports. The CRM is your Pipeline document and your contacts: the Pipeline Keeper is the only member that changes the pipeline, and every other member writes a document it reads. Nothing in the desk sends: the Quiet Deal Chaser and the Renewal Manager draft, and the person sends.
