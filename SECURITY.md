# Security policy

## Secrets

Never commit API keys (including GROQ_API_KEY and YOUTUBE_API_KEY), Google OAuth client JSON, OAuth refresh/access tokens, Groq keys, .env files, or generated credential files. Add credentials only through GitHub Actions repository secrets and rotate them immediately if disclosed.

TrendForge's public state file retains only short-lived deduplication identifiers and publishing records. It does not cache cross-channel view-count snapshots or commit production media.

## Workflow safety

- The publishing workflow runs only on the main branch from schedule or manual dispatch; it has no pull_request trigger.
- Review changes to the publishing pipeline before merging them into main. A malicious change to code on the trusted branch could exfiltrate workflow secrets.
- Protect main with a review requirement where practical. Do not grant push access to untrusted contributors.
- Keep the GITHUB_TOKEN permissions limited to contents: write, which the workflow needs only to persist the trend-history JSON. Do not add broad permissions without need.
- Secrets are exposed only to the pipeline step, not package installation or unit tests.
- Do not place credentials into logs, exception details, issue comments, generated scripts or artifacts.

## Reporting

For a security issue, avoid posting any secret, refresh token, or exploit that exposes credentials in a public issue. Rotate any exposed credentials first and report the issue privately to the repository maintainer.
