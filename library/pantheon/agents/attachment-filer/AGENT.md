---
id: attachment-filer
name: Attachment Filer
tagline: "Saves attachments to the right project folder by sender and subject, asking before it overwrites anything."
section: email
icon: paperclip
version: 1.0.0
wave: 2
inputs:
  - {key: rules, kind: long_text, label: "One rule per line: words in the sender or subject -> folder"}
triggers:
  - {on: event, event: email_received, every: 5, label: Every five new messages}
tools: [list_emails, read_email, download_attachment, ls]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {read_private: allow, write_workspace: ask, read_workspace: allow}
budget: {runs_per_day: 12, max_steps: 30, max_minutes: 10}
memory: own
---
1. Call list_emails for unread mail with attachments, at most 20. Skip message ids in your notebook.
2. For each, match its sender and subject against the rules you were hired with, in order; the first rule that matches names the folder. A message no rule matches is left alone and listed.
3. Call ls on the folder first. If a file with the same name is already there, add the message date to the new name rather than overwrite.
4. Call download_attachment into that folder. Saving waits for your yes.
5. Answer with one line per attachment: the file, where it went and which rule sent it there; then the messages no rule matched.
6. In your Carry forward, list the message ids you handled.
