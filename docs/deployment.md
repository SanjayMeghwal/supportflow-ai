# SupportFlow AI — Production Deployment Guide

This guide describes how to deploy SupportFlow AI on a standard Linux Virtual Private Server (Ubuntu 22.04 or 24.04 LTS) using Docker, Docker Compose, and an optional Nginx reverse proxy with TLS termination.

---

## Architecture Overview

```
                      Internet
                         │
                         ▼ (HTTPS :443)
              ┌─────────────────────┐
              │ Linux VPS (Host)    │
              │ Nginx (TLS / Edge)  │
              └──────────┬──────────┘
                         │
                         ▼ (HTTP :80)
┌─────────────────────────────────────────────────────────────┐
│ Docker Network: supportflow-prod-network                    │
│                                                             │
│   ┌─────────────────────┐                                   │
│   │ supportflow-frontend│ (Nginx static SPA + /api/ proxy)  │
│   └──────────┬──────────┘                                   │
│              │                                              │
│              ▼                                              │
│   ┌─────────────────────┐                                   │
│   │ supportflow-backend │ (FastAPI + Uvicorn)               │
│   └──────────┬──────────┘                                   │
│              │                                              │
│      ┌───────┴───────┐                                      │
│      ▼               ▼                                      │
│ ┌──────────┐   ┌──────────┐                                 │
│ │ Postgres │   │  Redis   │                                 │
│ │ pgvector │   │  (cache) │                                 │
│ └──────────┘   └──────────┘                                 │
│ (supportflow_   (supportflow_                               │
│  prod_pgdata)    prod_redisdata)                            │
└─────────────────────────────────────────────────────────────┘
```

### Key Security & Architecture Properties

1. **Zero Public Database/Cache Exposure:** PostgreSQL (`5432`) and Redis (`6379`) do **not** publish ports to the host interface. They are strictly reachable via the internal Docker bridge network (`supportflow-prod-network`).
2. **Backend Isolation:** The FastAPI backend is not directly published on the host. Traffic arrives via the frontend reverse proxy (port 80) or edge proxy (port 443).
3. **Non-Root Execution:** The backend container runs as dedicated user `appuser` (UID 10001).
4. **Persistent Storage:** PostgreSQL stores relational and vector data in a named Docker volume (`supportflow_prod_pgdata`). Redis persists to `supportflow_prod_redisdata`.
5. **Defense-in-Depth:** Containers enforce `security_opt: [no-new-privileges:true]`.

---

## 1. Prerequisites

- **Server:** Ubuntu 22.04 or 24.04 LTS (minimum 2 vCPUs, 4GB RAM recommended for PyTorch CPU embeddings).
- **Domain:** A registered domain or subdomain (e.g., `supportflow.yourdomain.com`) pointing to the server's public IPv4 address via an `A` record.
- **Access:** SSH access with `sudo` administrative privileges.
- **Docker Engine:** Version 24.0+ and Docker Compose v2.20+.

---

## 2. Server Preparation

Connect to your VPS via SSH and update system packages:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git ufw fail2ban
```

### Firewall Configuration (UFW)

Allow only SSH, HTTP, and HTTPS:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp comment 'SSH'
sudo ufw allow 80/tcp comment 'HTTP'
sudo ufw allow 443/tcp comment 'HTTPS'
sudo ufw enable
```

### Install Docker & Docker Compose

```bash
# Install Docker repository
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow current user to run Docker commands
sudo usermod -aG docker $USER
newgrp docker
```

---

## 3. Clone Repository & Setup Directory

Clone the repository to `/opt/supportflow` (or a dedicated application directory):

```bash
sudo mkdir -p /opt/supportflow
sudo chown -R $USER:$USER /opt/supportflow
git clone https://github.com/SanjayMeghwal/supportflow-ai.git /opt/supportflow
cd /opt/supportflow
```

---

## 4. Production Secret Generation & Configuration

Create your production environment file from the template:

```bash
cp .env.example .env
chmod 600 .env
```

### Generate Strong Secrets

Generate a cryptographically secure random secret for JWT signing:

```bash
openssl rand -hex 32
```

Generate a secure database password:

```bash
openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24
```

### Edit `.env` with Production Values

Open `.env` in an editor (`nano .env`) and set:

```env
APP_NAME="SupportFlow AI"
APP_ENV=production
DEBUG=False

# Secure Database Password
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_generated_postgres_password_here
POSTGRES_DB=supportflow_db

# Async Database URL (matches host 'db' in docker network)
DATABASE_URL=postgresql+asyncpg://postgres:your_generated_postgres_password_here@db:5432/supportflow_db

# Connection Pool Settings
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800

# Redis URL
REDIS_URL=redis://redis:6379/0

# Security Keys
JWT_SECRET_KEY=your_generated_jwt_secret_hex_32_chars
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# Reverse Proxy Trust
TRUST_PROXY_HEADERS=True

# CORS: Set to your exact production domain (no wildcard)
CORS_ORIGINS=https://supportflow.yourdomain.com
ENABLE_SECURITY_HEADERS=True
HSTS_ENABLED=True
ENABLE_DOCS=False

# LLM Provider Key
GROQ_API_KEY=gsk_your_real_groq_api_key_here
```

> [!CAUTION]
> Never commit `.env` to Git. Verify with `git status` that `.env` remains untracked.

---

## 5. Build & Start the Production Stack

Start the production stack using `docker-compose.prod.yml`:

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

### What Happens on Startup

1. **PostgreSQL 16 + pgvector (`db`)** starts, initializes storage in `supportflow_prod_pgdata`, and completes its healthcheck (`pg_isready`).
2. **Redis 7 (`redis`)** starts in append-only persistence mode (`--appendonly yes`) and passes `redis-cli ping`.
3. **Backend (`backend`)** begins execution via `/app/entrypoint.sh`:
   - Runs an async Python connectivity loop to ensure the database is fully responsive.
   - Automatically executes `alembic upgrade head` to apply all database migrations safely.
   - Launches Uvicorn running `backend.app.main:app` with production settings.
   - Reaches healthy status once `/health/ready` returns 200 OK.
4. **Frontend (`frontend`)** starts Nginx serving the compiled SPA and reverse-proxying `/api/` calls to `http://backend:8000/api/`.

---

## 6. Verification & Health Monitoring

Check running container status:

```bash
docker compose -f docker-compose.prod.yml ps
```

Expected output:
```
NAME                      STATUS                  PORTS
supportflow-prod-db       Up (healthy)            5432/tcp
supportflow-prod-redis    Up (healthy)            6379/tcp
supportflow-prod-backend  Up (healthy)            8000/tcp
supportflow-prod-frontend Up (healthy)            0.0.0.0:80->80/tcp
```

### Verify Endpoints Locally

```bash
# 1. Frontend health
curl -I http://localhost/healthz

# 2. Application liveness probe (does not query database)
curl -s http://localhost/api/v1/health/live

# 3. Application readiness probe (verifies PostgreSQL and Redis connectivity)
curl -s http://localhost/api/v1/health/ready

# 4. Public API root status
curl -s http://localhost/api/v1/
```

### Inspect Container Logs

```bash
# View backend logs (structured JSON format)
docker compose -f docker-compose.prod.yml logs -f backend

# View database logs
docker compose -f docker-compose.prod.yml logs db

# View all container logs
docker compose -f docker-compose.prod.yml logs --tail=100
```

---

## 7. Edge TLS / SSL Termination (Nginx + Certbot)

For production, run an edge Nginx reverse proxy on the host to terminate TLS and forward requests to the Docker container.

### Step 7.1: Install Host Nginx & Certbot

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

### Step 7.2: Configure Host Nginx

Copy the production Nginx configuration template from `deploy/nginx/supportflow.conf`:

```bash
sudo cp deploy/nginx/supportflow.conf /etc/nginx/sites-available/supportflow.conf
sudo ln -s /etc/nginx/sites-available/supportflow.conf /etc/nginx/sites-enabled/
```

Edit `/etc/nginx/sites-available/supportflow.conf` and replace `supportflow.example.com` with your actual domain name.

### Step 7.3: Obtain Let's Encrypt Certificate

```bash
sudo certbot --nginx -d supportflow.yourdomain.com
```

Test automatic certificate renewal:

```bash
sudo certbot renew --dry-run
```

---

## 8. Safe Application Update Flow

To deploy new code changes without downtime or database corruption:

```bash
# Step 1: Pull latest code
cd /opt/supportflow
git pull origin main

# Step 2: Backup the database before running migrations
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
docker compose -f docker-compose.prod.yml exec db \
  pg_dump -U postgres supportflow_db > /opt/supportflow/backups/backup_${TIMESTAMP}.sql

# Step 3: Rebuild images
docker compose -f docker-compose.prod.yml build

# Step 4: Restart containers with zero-downtime rolling restart
docker compose -f docker-compose.prod.yml up -d

# Step 5: Verify healthchecks pass
docker compose -f docker-compose.prod.yml ps
curl -s http://localhost/api/v1/health/ready
```

---

## 9. Database Backup & Disaster Recovery

### Manual Backup (`pg_dump`)

```bash
mkdir -p /opt/supportflow/backups
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U postgres -F c supportflow_db > /opt/supportflow/backups/supportflow_$(date +%F_%T).dump
```

### Automated Nightly Backup (Cron)

Add to root crontab (`sudo crontab -e`):

```cron
0 2 * * * cd /opt/supportflow && docker compose -f docker-compose.prod.yml exec -T db pg_dump -U postgres -F c supportflow_db > /opt/supportflow/backups/db_$(date +\%Y\%m\%d).dump && find /opt/supportflow/backups -type f -mtime +14 -delete
```

### Database Restore Procedure

To restore the database from a backup file:

```bash
# 1. Stop backend container to prevent concurrent writes
docker compose -f docker-compose.prod.yml stop backend

# 2. Restore database from dump
cat /opt/supportflow/backups/your_backup_file.dump | docker compose -f docker-compose.prod.yml exec -T db \
  pg_restore -U postgres -d supportflow_db --clean --if-exists

# 3. Restart backend and verify readiness
docker compose -f docker-compose.prod.yml start backend
curl -s http://localhost/api/v1/health/ready
```

---

## 10. Rollback Procedure

If an application release introduces unexpected behavior:

```bash
# 1. Check out the previous stable Git commit or tag
git checkout <previous-stable-commit-hash>

# 2. If a migration needs to be reverted, run Alembic downgrade:
docker compose -f docker-compose.prod.yml exec backend alembic downgrade -1

# 3. Rebuild and restart the containers
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# 4. Verify readiness
curl -s http://localhost/api/v1/health/ready
```

---

## 11. Troubleshooting Common Production Issues

| Issue | Root Cause | Solution |
|---|---|---|
| **Backend container exits on start** | Database not yet reachable or bad credentials | Check `docker compose -f docker-compose.prod.yml logs backend`. Verify `POSTGRES_PASSWORD` matches between `.env` and `DATABASE_URL`. |
| **Alembic migration fails on start** | Table lock or schema conflict | Check `docker compose logs backend`. If needed, run `alembic current` and resolve pending migration state. |
| **Readiness probe returns 503** | Redis or PostgreSQL connection failure | Inspect `curl -s http://localhost/api/v1/health/ready`. Check if Redis or DB container is healthy (`docker compose ps`). |
| **HTTP 413 Payload Too Large on upload** | Reverse proxy body size limit | Ensure `client_max_body_size 10M;` is configured in both host Nginx and frontend container Nginx. |
| **504 Gateway Timeout during RAG queries** | Reverse proxy read timeout exceeded | Ensure `proxy_read_timeout 120s;` is set in reverse proxy configuration. |
| **Rate limits trigger for all users on single IP** | `TRUST_PROXY_HEADERS` is disabled or reverse proxy does not set `X-Real-IP` | Verify `TRUST_PROXY_HEADERS=True` in `.env` and Nginx sets `proxy_set_header X-Real-IP $remote_addr;`. |
