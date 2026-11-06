---
id: the-books
name: The Books
tagline: "Money in order: the ledger, invoices, bills, the budget, the cash forecast, payroll, tax, and the subscriptions."
members: [bookkeeper, invoicing, ap-and-bills, budget-vs-actuals, cash-flow-forecaster, payroll-prep, tax-prep, expense-tracker, budget-watcher, bills-due, subscription-auditor, tax-folder-builder]
flow:
  - {from: bookkeeper, to: budget-vs-actuals, via: "document:Books"}
  - {from: bookkeeper, to: cash-flow-forecaster, via: "document:Books"}
  - {from: bookkeeper, to: tax-prep, via: "document:Books"}
  - {from: invoicing, to: cash-flow-forecaster, via: "document:Invoices"}
  - {from: bills-due, to: ap-and-bills, via: "document:Bills due"}
  - {from: ap-and-bills, to: cash-flow-forecaster, via: "document:Payment run"}
  - {from: payroll-prep, to: cash-flow-forecaster, via: "document:Payroll run"}
  - {from: tax-prep, to: tax-folder-builder, via: "document:Tax pack"}
---
Each member is its own hire with its own settings and reports. The Bookkeeper keeps the ledger (`ledger_table`) that the rest read: invoices raised, bills staged, payroll lines, the budget's actuals, the cash forecast and the tax pack all come from the same rows. Nothing in the team pays, sends or files: every payment run, invoice and payroll run is a document the person checks and acts on, and none of it is tax or accounting advice.
