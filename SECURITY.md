# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in flow-memory, please report it
privately to the maintainers. **Do not file a public GitHub issue.**

Contact: security@flow-memory.local

Please include:
- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Potential impact

## Response Timeline

- **Acknowledgement**: within 3 business days
- **Initial assessment**: within 7 business days
- **Fix timeline**: depends on severity
  - Critical: within 24-48 hours
  - High: within 1 week
  - Medium: within 2 weeks
  - Low: next minor release

## Security Features

flow-memory implements several security best practices:

### Sensitive Data Encryption

- AES-256-GCM authenticated encryption
- PBKDF2-HMAC-SHA256 with 480,000 iterations (OWASP-recommended)
- Per-message random nonces (12 bytes)
- Authentication tags prevent tampering
- Audit log automatically redacts password fields

### Authentication & Authorization

- PromotionPolicy ABC allows host customization
- Default: high-impact kinds require authorized reviewers
- Configurable per-deployment

### Local-First Storage

- Data stays on user's machine by default
- No telemetry or external network calls
- User controls backup/sync

### Audit Trail

- All sensitive operations logged to `audit.log`
- Sensitive fields auto-redacted
- Failed access attempts tracked

### Known Limitations

- Single-user mode (no multi-tenant authentication)
- Local SQLite/Postgres files assume local filesystem permissions
- Memory CLI runs with user's privileges (no sandboxing)

## Cryptographic Details

| Component | Algorithm | Parameters |
|-----------|-----------|------------|
| Password hashing | PBKDF2-HMAC-SHA256 | 480,000 iterations, 32-byte salt |
| Memory encryption | AES-256-GCM | 256-bit key, 12-byte nonce |
| Salt generation | OS CSPRNG | 32 bytes |
| Nonce generation | OS CSPRNG | 12 bytes per encryption |

## Disclosure Policy

We follow responsible disclosure:

1. Security issue reported privately
2. We investigate and develop fix
3. Fix released in patch version
4. After 30 days, public disclosure with credit to reporter (if desired)

## Out of Scope

The following are out of scope for security reports:

- Denial-of-service attacks against local-only infrastructure
- Social engineering
- Physical attacks
- Issues in third-party dependencies (report upstream)