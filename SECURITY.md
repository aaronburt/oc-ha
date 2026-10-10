# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's
[private vulnerability reporting](https://github.com/aaronburt/oc-ha/security/advisories/new)
instead of opening a public issue.

Useful reports include issues with API key handling, request or diagnostics
logging that exposes data, and anything that lets a model act on Home
Assistant entities beyond what the agent options allow.

## Scope

This is a community integration. It sends your OpenCode Go API key and
conversation traffic to `opencode.ai`; that behaviour is by design and
documented in the integration's help text and the model picker.
