# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in Remote Control, please report it responsibly.

### How to Report

1. **Do not** open a public GitHub issue for security vulnerabilities.
2. Send a report to the project maintainers via [GitHub Security Advisories](../../security/advisories/new).
3. Include the following information:
   - A description of the vulnerability
   - Steps to reproduce
   - Affected versions
   - Potential impact
   - Any suggested mitigation or fix (optional)

### What to Expect

- We will acknowledge your report within 48 hours.
- We will investigate and provide an initial assessment within 5 business days.
- We will keep you informed of progress throughout the resolution process.
- We will credit you in the advisory (unless you prefer to remain anonymous).

### Responsible Disclosure

We ask that you:

- Give us a reasonable amount of time to fix the issue before public disclosure.
- Do not access or modify other users' data.
- Do not degrade service availability.
- Act in good faith to protect users' privacy and security.

## Security Best Practices

When deploying Remote Control:

- **Always** set `JWT_SECRET` to a strong random value. Generate with `openssl rand -hex 32`.
- **Always** set `REDIS_PASSWORD` to a strong, unique password.
- Use HTTPS/WSS in production (via a reverse proxy or Traefik gateway).
- Restrict network access with firewalls or security groups.
- Keep dependencies up to date.
- Do not expose development configurations to the public internet.
- Rotate secrets periodically and after any suspected compromise.
