---
id: unsubscribe-sweeper
name: Unsubscribe Sweeper
tagline: Finds the senders you never open and lists the unsubscribe link for each — unsubscribing only when you say.
section: email
icon: mail-x
version: 1.0.0
wave: 2
inputs:
  - {key: months, kind: number, label: Never opened for this many months, default: 3}
triggers:
  - {on: cron, cron: "20 9 1 * *", label: The first of each month}
tools: [scan_email_unsubscribes, search_emails, create_document, unsubscribe_email]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: document, title: "Unsubscribe list"}
effects: {read_private: allow, write_private: allow, external_side_effect: ask}
budget: {runs_per_day: 2, max_steps: 30, max_minutes: 15}
memory: own
---
1. Call scan_email_unsubscribes to list senders that offer an unsubscribe link.
2. For each, use search_emails to see whether you have read any of their mail in the months you were hired with. Keep only the senders you never opened.
3. Call create_document titled "Unsubscribe list" and the date: one line per sender — name, address, how many messages in the period, and the unsubscribe link exactly as found.
4. Only for a sender listed in your notebook under "approved", call unsubscribe_email. That call waits for your yes; if it is refused, leave the sender on the list.
5. In your Carry forward, write "approved:" followed by nothing — a person adds senders there by editing the notebook — then the senders you listed this month.
