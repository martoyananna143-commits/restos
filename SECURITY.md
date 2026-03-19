# Security Configuration Guide

## Overview

This document describes the security measures implemented in the Yarbot API and how to configure them properly for production deployment.

## ✅ Implemented Security Measures

### 1. API Authentication & Authorization

All API endpoints (except `/health`, `/`, and `/api/webapp/*`) now require authentication via Telegram headers:

- `X-Telegram-Id`: Telegram user ID
- `X-Telegram-Chat-Id`: Telegram chat ID  
- `X-Organization-Id`: Organization ID (for organization-specific endpoints)

**Authentication layers:**
- `get_current_user()` - Validates Telegram user
- `get_current_employee()` - Validates employee access to organization
- `require_admin()` - Requires administrator privileges

**Protected endpoints:**
- `/api/v1/organizations` - Organization management (admin required for modifications)
- `/api/v1/criteria` - Criteria management (admin required for create/update)
- `/api/v1/analytics` - Analytics data (employee access required)
- `/api/v1/evaluations` - Evaluations (employee access required)
- All other `/api/v1/*` endpoints

### 2. Network Security (docker-compose.yml)

**Database ports closed:**
- PostgreSQL (5432) - NOT exposed externally
- Redis (6379) - NOT exposed externally
- Only internal Docker network access

**Exposed ports:**
- Port 8000 - Bot API (consider putting behind reverse proxy in production)
- Port 8080 - Dioxus form (consider putting behind reverse proxy in production)

**Network isolation:**
- All services communicate via internal Docker network `restos_internal`
- Set `internal: true` in network config for complete isolation if needed

### 3. CORS Configuration

CORS is now configurable via environment variables:

```bash
# Development (default)
CORS_ORIGINS="*"

# Production (recommended)
CORS_ORIGINS="https://yourdomain.com,https://webapp.yourdomain.com"
CORS_ALLOW_CREDENTIALS=true
```

**Allowed headers:**
- `Content-Type`
- `Authorization`
- `X-Telegram-Id`
- `X-Telegram-Chat-Id`
- `X-Organization-Id`

### 4. Web App Token Security

The `/api/webapp/*` endpoints use ChaCha20Poly1305 encryption for stateless tokens:

- **Token encryption**: 32-byte key (ChaCha20Poly1305)
- **Token expiry**: Configurable (default 1 hour)
- **Replay protection**: Tokens are marked as used after submission
- **No session storage**: All data embedded in encrypted token

**Configuration:**
```bash
# Generate key: python -c "import secrets; print(secrets.token_hex(32))"
WEBAPP_SECRET_KEY=<64_hex_characters>
WEBAPP_TOKEN_EXPIRY=3600  # seconds
```

## 🔴 Critical: Production Deployment Checklist

### Before deploying to production:

#### 1. Environment Variables

Create `.env` file with:

```bash
# Bot Configuration
TGBOT_TOKEN=<your_bot_token>
TGBOT_ADMIN_IDS=123456789,987654321

# Database (use strong password!)
POSTGRES_PASSWORD=<strong_random_password>
DATABASE_URL=postgresql+asyncpg://postgres:<password>@postgres:5432/restos

# Redis
REDIS_DSN=redis://redis:6379/0

# Web App Security
WEBAPP_SECRET_KEY=<generate_with_secrets.token_hex(32)>
WEBAPP_TOKEN_EXPIRY=3600
WEBAPP_BASE_URL=https://forms.yourdomain.com

# CORS (CRITICAL!)
CORS_ORIGINS="https://yourdomain.com,https://webapp.yourdomain.com"
CORS_ALLOW_CREDENTIALS=true
```

#### 2. Docker Network

In `docker-compose.yml`, set network to internal for complete isolation:

```yaml
networks:
  restos_internal:
    driver: bridge
    internal: true  # No external access - only through reverse proxy
```

#### 3. Reverse Proxy (Nginx)

Configure `docker/nginx/nginx.conf`:

```nginx
# Enable HTTPS
# Uncomment HTTPS server block
# Configure SSL certificates
# Redirect HTTP to HTTPS

# Rate limiting
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

location /api/ {
    limit_req zone=api_limit burst=20 nodelay;
    proxy_pass http://fastapi;
    # ... other settings
}
```

#### 4. Additional Security Headers

Add to Nginx config:

```nginx
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
```

#### 5. Database Security

```bash
# Change default passwords
POSTGRES_PASSWORD=<strong_random_password>

# Backup strategy
# Set up regular backups of restos_postgres_data volume

# Consider using connection pooling limits
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
```

## 🛡️ Security Best Practices

### 1. Telegram Web App Validation

The current implementation trusts `X-Telegram-Id` headers. For production, implement Telegram Web App initData validation:

```python
# TODO: Add Telegram Web App initData validation
# See: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
```

### 2. Rate Limiting

Consider adding rate limiting middleware:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.get("/api/v1/analytics")
@limiter.limit("5/minute")
async def analytics(...):
    ...
```

### 3. Input Validation

All inputs are validated via Pydantic schemas. Additional validation for:
- SQL injection prevention (using SQLAlchemy ORM)
- XSS prevention (sanitize user inputs in reports)
- CSRF protection (tokens are one-time use)

### 4. Logging & Monitoring

```yaml
# Current log limits (docker-compose.yml)
logging:
  driver: "json-file"
  options:
    max-size: "200k"  # Consider increasing for production
    max-file: "10"

# TODO: Add centralized logging
# - ELK stack
# - Prometheus + Grafana
# - Error tracking (Sentry)
```

### 5. Secrets Management

Do NOT commit secrets to git:
- Use `.env` file (already in `.gitignore`)
- For production, consider using:
  - Docker secrets
  - Kubernetes secrets
  - HashiCorp Vault
  - AWS Secrets Manager

## 🔍 Testing Security

### Test authentication:

```bash
# Should fail (401 Unauthorized)
curl -X GET http://localhost:8000/api/v1/organizations

# Should succeed
curl -X GET http://localhost:8000/api/v1/organizations \
  -H "X-Telegram-Id: 123456789" \
  -H "X-Telegram-Chat-Id: 123456789" \
  -H "X-Organization-Id: 1"
```

### Test CORS:

```bash
curl -X OPTIONS http://localhost:8000/api/v1/organizations \
  -H "Origin: https://malicious-site.com" \
  -H "Access-Control-Request-Method: GET"

# Should reject if CORS_ORIGINS is configured
```

### Test database access:

```bash
# Should fail (connection refused) from outside Docker network
psql -h localhost -p 5432 -U postgres -d restos
```

## 📋 Vulnerability Response

If you discover a security vulnerability:

1. **DO NOT** create a public GitHub issue
2. Contact the maintainers directly
3. Provide detailed information:
   - Description of vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## 🔄 Regular Security Maintenance

- [ ] Update dependencies monthly: `poetry update`
- [ ] Review Docker image versions quarterly
- [ ] Rotate `WEBAPP_SECRET_KEY` periodically
- [ ] Review access logs for suspicious activity
- [ ] Audit user permissions regularly
- [ ] Test backup restoration procedure
- [ ] Review and update CORS origins as needed

## 📚 Additional Resources

- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Telegram Bot Security](https://core.telegram.org/bots/api#authorizing-your-bot)

---

**Last Updated:** 2026-02-08

**Security Review Status:** ✅ Initial security measures implemented
**Next Review Due:** 2026-03-08
