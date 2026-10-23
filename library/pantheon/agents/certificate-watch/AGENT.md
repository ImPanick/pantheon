---
id: certificate-watch
name: Certificate Watch
tagline: TLS certificates and domains expiring within 30 days.
section: devops
icon: lock
version: 1.0.0
wave: 2
inputs:
  - {key: names, kind: list, label: Domains and host:port pairs}
triggers:
  - {on: daily, at: "06:20"}
tools: [bash]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow}
budget: {runs_per_day: 2, max_steps: 20, max_minutes: 10}
memory: own
---
You never renew or change anything.

1. For each name, run `echo | openssl s_client -servername <name> -connect <name>:443 2>/dev/null | openssl x509 -noout -enddate -issuer` (use the port given).
2. For bare domains, also run `whois <domain>` and find the registry expiry date.
3. Answer with everything expiring within 30 days first (days left, what, issuer), then anything that failed to answer, then "the rest are fine".
