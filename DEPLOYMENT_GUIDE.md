# Save Shop Production Deployment & Server Operations Guide

> **Author**: Antigravity Pair Programming  
> **Last Updated**: October 2026  
> **Platform**: Ubuntu 24.04 LTS (Proxmox NAT LXC Container)  
> **Status**: Production Live & Fully Automated CI/CD  

---

## 1. System Architecture Overview

```
                      Internet Clients (Web Browser / Mobile App)
                                          │
                                          ▼
                HTTPS Traffic (SSL/TLS managed automatically)
                                          │
                                          ▼
                      ┌───────────────────────────────────────┐
                      │    Cloudflare Edge / Quick Tunnel     │
                      └───────────────────┬───────────────────┘
                                          │ Encrypted Tunnel
                                          ▼
                      ┌───────────────────────────────────────┐
                      │        VPS (148.113.9.217:20016)       │
                      │         cloudflared daemon            │
                      └───────────────────┬───────────────────┘
                                          │ HTTP 127.0.0.1:80
                                          ▼
                      ┌───────────────────────────────────────┐
                      │          Nginx Web Server             │
                      ├───────────────────┬───────────────────┤
                      │   Route: /        │   Route: /api/    │
                      │   (React Static)  │   (Reverse Proxy) │
                      └─────────┬─────────┴─────────┬─────────┘
                                │                   │
                                ▼                   ▼
                      ┌──────────────────┐ ┌───────────────────┐
                      │ Frontend Assets  │ │ Save Shop Backend │
                      │ /var/www/save-   │ │ FastAPI / Uvicorn │
                      │ shop-frontend/   │ │ (127.0.0.1:8000)  │
                      │ dist/            │ └─────────┬─────────┘
                      └──────────────────┘           │
                                                     ▼
                                           ┌───────────────────┐
                                           │ PostgreSQL 16 DB  │
                                           │ (localhost:5432)  │
                                           │ DB: saveshop_db   │
                                           └───────────────────┘
```

### Why this architecture?
1. **Zero Domain / NAT Bypass**: The VPS sits behind a NAT internal IP (`10.10.10.18`) where public ports 80/443 are blocked by the provider. Cloudflare Tunnel creates an outbound persistent TLS tunnel, delivering **valid HTTPS with automated SSL renewal** without requiring a purchased domain or inbound port forwarding.
2. **Unified Single-Origin Routing**: Nginx serves the React/Expo Web SPA bundle on `/` and reverse-proxies `/api/` to FastAPI. This eliminates browser CORS issues, cookie security restrictions, and hardcoded origin problems on the web.
3. **Low-RAM Stability**: Configured virtual memory, lightweight uvicorn workers, and automated watchdog scripts ensure the system remains stable on a 1GB RAM budget.

---

## 2. Server Specifications & Production Credentials

| Parameter | Production Value |
| :--- | :--- |
| **Host IP** | `148.113.9.217` |
| **SSH Port** | `20016` |
| **SSH User** | `root` |
| **Internal IP** | `10.10.10.18` (NAT Container) |
| **PostgreSQL Version** | PostgreSQL 16 |
| **PostgreSQL DB Name** | `saveshop_db` |
| **PostgreSQL User** | `saveshop_user` |
| **PostgreSQL Password** | `SaveShopPass_9217_Secure!` |
| **PostgreSQL Port** | `5432` |
| **Live Web App URL** | `https://chamber-golf-guardian-thumbnails.trycloudflare.com/` |
| **Backend API Docs** | `https://chamber-golf-guardian-thumbnails.trycloudflare.com/docs` |

---

## 3. Directory Structure on VPS

```
/etc/saveshop/
├── backend.env               <-- Production backend secrets (chmod 600, root only)
├── frontend.env              <-- Production frontend secrets (chmod 600, root only)
└── current_tunnel_url.txt    <-- Active Cloudflare Tunnel URL

/var/www/
├── save-shop-backend/        <-- FastAPI application repository
│   ├── .env                  <-- Symlink pointing to /etc/saveshop/backend.env
│   ├── venv/                 <-- Isolated Python virtual environment
│   └── main.py
└── save-shop-frontend/
    └── dist/                 <-- Exported React/Expo Web static production build

/etc/systemd/system/
├── save-shop-backend.service <-- Backend systemd service
└── saveshop-startup.service  <-- Server boot & recovery watchdog service

/usr/local/bin/
├── cloudflared               <-- Cloudflare tunnel binary
└── saveshop-startup.sh       <-- Auto-recovery watchdog script
```

---

## 4. Complete Step-by-Step Server Setup (Replication Guide)

Follow these exact steps if provisioning a fresh Ubuntu VPS from scratch:

### Step 1: Base System Update & Essential Tools
```bash
# Update package repositories and upgrade existing packages
apt update && apt upgrade -y

# Install required build tools, networking utilities, and git
apt install -y curl wget git build-essential software-properties-common nginx ufw
```

### Step 2: Fix IPv6 DNS Resolution Delay (Critical for Google Auth & APIs)
Unroutable IPv6 interfaces cause 20+ second delays when contacting Google SSO or GitHub APIs. Force IPv4 precedence:
```bash
echo "precedence ::ffff:0:0/96 100" >> /etc/gai.conf
```

### Step 3: Install & Configure PostgreSQL 16
```bash
# Install PostgreSQL 16 and client tools
apt install -y postgresql postgresql-contrib

# Start and enable PostgreSQL service on system boot
systemctl enable postgresql
systemctl start postgresql

# Create dedicated database and secure application user
sudo -u postgres psql << 'EOF'
CREATE DATABASE saveshop_db;
CREATE USER saveshop_user WITH ENCRYPTED PASSWORD 'SaveShopPass_9217_Secure!';
GRANT ALL PRIVILEGES ON DATABASE saveshop_db TO saveshop_user;
ALTER DATABASE saveshop_db OWNER TO saveshop_user;
\c saveshop_db
GRANT ALL ON SCHEMA public TO saveshop_user;
EOF
```

#### How to Expose PostgreSQL for Local pgAdmin Connection
1. Edit `/etc/postgresql/16/main/postgresql.conf`:
   ```bash
   sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" /etc/postgresql/16/main/postgresql.conf
   ```
2. Allow md5 password authentication in `/etc/postgresql/16/main/pg_hba.conf`:
   ```bash
   echo "host    saveshop_db     saveshop_user    0.0.0.0/0               scram-sha-256" >> /etc/postgresql/16/main/pg_hba.conf
   systemctl restart postgresql
   ```
3. **Connect in pgAdmin**:
   - **Recommended & Secure**: In pgAdmin > Register Server > Connection: `Host: localhost`, `Port: 5432`, `Maintenance Database: saveshop_db`, `Username: saveshop_user`. In the **SSH Tunnel** tab: `SSH Host: 148.113.9.217`, `Port: 20016`, `Username: root`.

### Step 4: Python 3.12 & Backend Application Setup
```bash
# Install Python 3.12, venv, and dev headers
apt install -y python3 python3-pip python3-venv libpq-dev

# Clone backend repository
git clone https://github.com/AkashBapiBag/Save-shop-backend.git /var/www/save-shop-backend
cd /var/www/save-shop-backend

# Create virtual environment and install dependencies
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install requests psycopg2-binary
```

### Step 5: Secure Environment Files Setup
```bash
# Create protected directory
mkdir -p /etc/saveshop
chmod 700 /etc/saveshop

# Create production backend environment file
cat << 'EOF' > /etc/saveshop/backend.env
ENVIRONMENT=production
DEBUG=False
PROJECT_NAME="Save Shop API"
VERSION="1.0.0"
API_V1_STR="/api/v1"
DATABASE_URL=postgresql+psycopg2://saveshop_user:SaveShopPass_9217_Secure!@localhost:5432/saveshop_db
SECRET_KEY=3d57f864e402e3b2e7960359cb87889ffcb8d3b51610e2f5b61073dc76b15e21
ACCESS_TOKEN_EXPIRE_MINUTES=10080
GOOGLE_SSO_ENABLED=True
GOOGLE_CLIENT_ID=898498745806-g40fimuhq99o7aohltn4qqinpvog31d5.apps.googleusercontent.com
GOOGLE_ALLOWED_CLIENT_IDS=["898498745806-gnrm36ifk3qoek9et2ej5o6ajrrc1bbm.apps.googleusercontent.com"]
ADMIN_EMAILS=["akashbapibag9@gmail.com"]
ENABLE_DEV_DIRECT_LOGIN=False
EOF
chmod 600 /etc/saveshop/backend.env

# Symlink .env in the backend folder
ln -sf /etc/saveshop/backend.env /var/www/save-shop-backend/.env
```

### Step 6: Create Backend Systemd Service
Create `/etc/systemd/system/save-shop-backend.service`:
```ini
[Unit]
Description=Save Shop Backend FastAPI Application
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/save-shop-backend
EnvironmentFile=/etc/saveshop/backend.env
ExecStart=/var/www/save-shop-backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start backend:
```bash
systemctl daemon-reload
systemctl enable save-shop-backend
systemctl start save-shop-backend
```

### Step 7: Configure Nginx (Frontend & Reverse Proxy)
Create `/etc/nginx/sites-available/saveshop`:
```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    server_name _;
    client_max_body_size 50M;

    root /var/www/save-shop-frontend/dist;
    index index.html;

    # Frontend Single Page App history routing
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Swagger / OpenAPI documentation
    location ~ ^/(docs|redoc|openapi.json) {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend API routes with preflight CORS headers
    location /api/ {
        if ($request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin' '$http_origin' always;
            add_header 'Access-Control-Allow-Credentials' 'true' always;
            add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, PATCH, OPTIONS' always;
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization,X-Store-Id,X-Dev-User-Email' always;
            add_header 'Access-Control-Max-Age' 1728000 always;
            add_header 'Content-Type' 'text/plain; charset=utf-8' always;
            add_header 'Content-Length' 0 always;
            return 204;
        }

        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;

        proxy_hide_header Access-Control-Allow-Origin;
        proxy_hide_header Access-Control-Allow-Credentials;
        add_header 'Access-Control-Allow-Origin' '$http_origin' always;
        add_header 'Access-Control-Allow-Credentials' 'true' always;
    }
}
```

Enable Nginx site and test configuration:
```bash
mkdir -p /var/www/save-shop-frontend/dist
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/saveshop /etc/nginx/sites-enabled/saveshop
nginx -t
systemctl restart nginx
systemctl enable nginx
```

### Step 8: Install Cloudflare Tunnel (`cloudflared`)
```bash
# Download and install cloudflared
curl -L --output /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /usr/local/bin/cloudflared
```

---

## 5. Auto-Startup & Recovery Watchdog (Server Reboot Protection)

To guarantee that all services restart automatically if the server reboots due to high memory load, kernel updates, or hosting downtime, we have installed a resilient dual-layer watchdog system.

### The Watchdog Script: `/usr/local/bin/saveshop-startup.sh`
```bash
#!/usr/bin/env bash
LOG_FILE="/var/log/saveshop-startup.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Save Shop services check..." >> "$LOG_FILE"

# 1. PostgreSQL
if ! systemctl is-active --quiet postgresql; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] PostgreSQL was down. Starting..." >> "$LOG_FILE"
    systemctl restart postgresql
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] PostgreSQL is running." >> "$LOG_FILE"
fi

# 2. Save Shop Backend (FastAPI)
if ! systemctl is-active --quiet save-shop-backend; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backend was down. Starting..." >> "$LOG_FILE"
    ln -sf /etc/saveshop/backend.env /var/www/save-shop-backend/.env
    systemctl restart save-shop-backend
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backend is running." >> "$LOG_FILE"
fi

# 3. Nginx Reverse Proxy
if ! systemctl is-active --quiet nginx; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nginx was down. Starting..." >> "$LOG_FILE"
    systemctl restart nginx
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nginx is running." >> "$LOG_FILE"
fi

# 4. Cloudflare HTTPS Tunnel
if ! pgrep -f "cloudflared tunnel" > /dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cloudflared tunnel was not running. Starting..." >> "$LOG_FILE"
    nohup /usr/local/bin/cloudflared tunnel --url http://127.0.0.1:80 --logfile /var/log/cloudflared.log > /dev/null 2>&1 &
    sleep 4
    CURRENT_URL=$(grep -o 'https://[-a-z0-9]*\.trycloudflare\.com' /var/log/cloudflared.log | tail -n 1)
    if [ -n "$CURRENT_URL" ]; then
        echo "$CURRENT_URL" > /etc/saveshop/current_tunnel_url.txt
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] New Tunnel URL: $CURRENT_URL" >> "$LOG_FILE"
    fi
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cloudflared tunnel is active." >> "$LOG_FILE"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Save Shop healthcheck completed successfully." >> "$LOG_FILE"
```

### Registered Triggers:
1. **Systemd Service**: `/etc/systemd/system/saveshop-startup.service` is `enabled` (`WantedBy=multi-user.target`).
2. **Cron Watchdog**:
   ```bash
   */5 * * * * /usr/local/bin/saveshop-startup.sh >/dev/null 2>&1
   @reboot /usr/local/bin/saveshop-startup.sh >/dev/null 2>&1
   ```

---

## 6. How to Update Environment Variables in Production

Never edit `.env` in Git repositories. To change backend or frontend configurations:

### Updating Backend Environment Variables
1. SSH into the server:
   ```bash
   ssh root@148.113.9.217 -p 20016
   ```
2. Edit `/etc/saveshop/backend.env`:
   ```bash
   nano /etc/saveshop/backend.env
   ```
3. Restart the backend service:
   ```bash
   systemctl restart save-shop-backend
   ```
4. Check that it started cleanly:
   ```bash
   systemctl status save-shop-backend
   journalctl -u save-shop-backend -n 30 --no-pager
   ```

### Updating Frontend Environment Variables in GitHub CI/CD
1. Go to GitHub: **Save-shop** repository > **Settings** > **Secrets and variables** > **Actions**.
2. Update any of the encrypted repository secrets:
   - `EXPO_PUBLIC_API_URL`
   - `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID`
   - `EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID`
3. Trigger the deployment either by pushing a commit to `main` or going to **Actions** > **Test, Build and Deploy Save Shop Frontend to VPS** > **Run workflow**.

---

## 7. Server Logging, Real-Time Debugging & Safe Log Cleanup

All server application requests, error tracebacks, Nginx traffic, and recovery watchdog events are persistently logged to disk in standard Unix log directories with automated rotation and instant CLI tools.

### Log File Locations

| Component | Path on Server | Purpose |
| :--- | :--- | :--- |
| **Backend Live Requests** | `/var/log/saveshop/backend.log` | Every HTTP request (IP, timestamp, route, status code, latency) |
| **Backend Error Stacktraces** | `/var/log/saveshop/backend-error.log` | Unhandled exceptions, 500 errors, database connection issues |
| **Recovery Watchdog Log** | `/var/log/saveshop-startup.log` | Records every reboot and 5-min healthcheck recovery event |
| **Nginx Access Log** | `/var/log/nginx/access.log` | Raw incoming HTTP/HTTPS requests hitting Nginx |
| **Nginx Error Log** | `/var/log/nginx/error.log` | Bad gateway (502), upstream timeouts (504), routing errors |
| **Cloudflare Tunnel Log** | `/var/log/cloudflared.log` | Outbound TLS tunnel health and public URL assignment |

---

### Instant Log Viewer: `saveshop-logs` Utility

A dedicated helper script has been placed at `/usr/local/bin/saveshop-logs` for fast debugging over SSH:

```bash
# 1. View live backend requests in real time (follows new incoming traffic)
saveshop-logs

# 2. View latest 50 backend error stacktraces (for fast bug inspection)
saveshop-logs error

# 3. View live Nginx requests and errors
saveshop-logs nginx

# 4. View auto-recovery watchdog status
saveshop-logs startup

# 5. Check disk space used by all log files
saveshop-logs size

# 6. Safely truncate all log files to 0 bytes (frees disk space without restarting services)
saveshop-logs clean
```

---

### Standard Linux Commands for Manual Log Inspection

If you prefer standard shell commands:
```bash
# Follow backend logs live:
tail -f /var/log/saveshop/backend.log

# Search for 500 Internal Server Errors in backend:
grep " 500 " /var/log/saveshop/backend.log

# Search for specific error messages or stack traces:
tail -n 100 /var/log/saveshop/backend-error.log

# Follow Nginx proxy traffic:
tail -f /var/log/nginx/access.log /var/log/nginx/error.log

# Check disk space used by all logs:
ls -lh /var/log/saveshop/ /var/log/nginx/
```

---

### How to Manually Clean Logs to Free Disk Space

On a low-disk VPS, you can safely wipe logs at any time without stopping running services using `truncate`:
```bash
# Option A: One-click command via helper
saveshop-logs clean

# Option B: Manual truncate commands
truncate -s 0 /var/log/saveshop/*.log
truncate -s 0 /var/log/nginx/*.log
truncate -s 0 /var/log/saveshop-startup.log
```
> [!NOTE]
> Always use `truncate -s 0 <file>` instead of `rm <file>`. `truncate` clears the file contents in-place so running processes (Uvicorn, Nginx) do not lose their file descriptors.

---

### Automated Log Rotation (`/etc/logrotate.d/saveshop`)

To ensure the server disk **never fills up**, automated daily log rotation is active:
- Rotates logs **daily**.
- Keeps **7 days** of history.
- Automatically **compresses** old logs (`.gz`).
- Uses `copytruncate` to safely rotate active logs without service downtime.

---

## 8. Crash & Emergency Management Commands

| Task | Command |
| :--- | :--- |
| **Check All Services Status** | `systemctl status postgresql nginx save-shop-backend` |
| **Run Health Check Watchdog** | `/usr/local/bin/saveshop-startup.sh && cat /var/log/saveshop-startup.log` |
| **Restart Backend Service** | `systemctl restart save-shop-backend` |
| **View Live Backend Logs** | `saveshop-logs` or `tail -f /var/log/saveshop/backend.log` |
| **View Latest Backend Errors** | `saveshop-logs error` |
| **Clean All Log Files** | `saveshop-logs clean` |
| **Restart Nginx** | `systemctl restart nginx` |
| **View Live Nginx Error Log** | `tail -f /var/log/nginx/error.log` |
| **Find Active Tunnel URL** | `cat /etc/saveshop/current_tunnel_url.txt` |
| **Restart Cloudflare Tunnel** | `pkill -f cloudflared && /usr/local/bin/saveshop-startup.sh` |
| **Connect to PostgreSQL DB** | `sudo -u postgres psql -d saveshop_db` |
| **Backup PostgreSQL DB** | `sudo -u postgres pg_dump saveshop_db > /etc/saveshop/backup_$(date +%F).sql` |
| **Restore PostgreSQL DB** | `sudo -u postgres psql saveshop_db < /etc/saveshop/backup_YYYY-MM-DD.sql` |
| **Check RAM & Virtual Swap** | `free -h` |
