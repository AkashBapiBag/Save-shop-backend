# Save Shop Production Deployment & Server Operations Guide

> **Author**: Antigravity Pair Programming  
> **Last Updated**: October 2026  
> **Platform**: Ubuntu 24.04 LTS (Proxmox NAT LXC Container / Standard KVM VPS)  
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
                                          │ Encrypted Outbound Tunnel
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
1. **Zero Domain / NAT Bypass**: The VPS sits behind an internal NAT IP (`10.10.10.18`) where standard public ports 80/443 are blocked by the provider. Cloudflare Tunnel creates an outbound persistent TLS tunnel, delivering **valid HTTPS with automated SSL renewal** without requiring a purchased domain or inbound router port forwarding.
2. **Unified Single-Origin Routing**: Nginx serves the React/Expo Web SPA bundle on `/` and reverse-proxies `/api/` to FastAPI on the same port. This eliminates browser CORS preflight overhead, cookie security restrictions, and hardcoded origin problems on the web.
3. **Low-RAM Stability**: Configured virtual memory, lightweight uvicorn workers, and an automated watchdog script ensure the system runs smoothly on a 1GB RAM budget.

---

## 2. Server Specifications & Production Credentials

| Parameter | Production Value | Description |
| :--- | :--- | :--- |
| **Host IP** | `148.113.9.217` | Public VPS Gateway IP |
| **SSH Port** | `20016` | Mapped SSH Port (internal port 22) |
| **SSH User** | `root` | Root administrator |
| **Internal IP** | `10.10.10.18` | Private NAT Container IP |
| **PostgreSQL Version** | PostgreSQL 16 | Relational database engine |
| **PostgreSQL DB Name** | `saveshop_db` | Application database |
| **PostgreSQL User** | `saveshop_user` | Application database user |
| **PostgreSQL Password** | `SaveShopPass_9217_Secure!` | Application database password |
| **PostgreSQL Port** | `5432` | Standard PostgreSQL port |
| **Live Web App URL** | `https://chamber-golf-guardian-thumbnails.trycloudflare.com/` | Public HTTPS Web App |
| **Backend API Docs** | `https://chamber-golf-guardian-thumbnails.trycloudflare.com/docs` | Swagger / OpenAPI Explorer |

---

## 3. Directory Structure on VPS

```
/etc/saveshop/
├── backend.env               <-- Production backend secrets (chmod 600, root only)
├── frontend.env              <-- Production frontend secrets (chmod 600, root only)
├── current_tunnel_url.txt    <-- Active Cloudflare Tunnel URL
└── DEPLOYMENT_GUIDE.md       <-- Exact copy of this operations manual

/var/www/
├── save-shop-backend/        <-- FastAPI application repository
│   ├── .env                  <-- Symlink pointing to /etc/saveshop/backend.env
│   ├── venv/                 <-- Isolated Python virtual environment
│   └── main.py
└── save-shop-frontend/
    └── dist/                 <-- Exported React/Expo Web static production build

/var/log/
├── saveshop/
│   ├── backend.log           <-- Real-time HTTP access & status code logs
│   └── backend-error.log     <-- Error stack traces and 500 exceptions
├── saveshop-startup.log      <-- Auto-recovery watchdog history
└── cloudflared.log           <-- Cloudflare tunnel status & assigned URLs

/etc/systemd/system/
├── save-shop-backend.service <-- Backend systemd service
└── saveshop-startup.service  <-- Server boot & recovery watchdog service

/usr/local/bin/
├── cloudflared               <-- Cloudflare tunnel binary
├── saveshop-startup.sh       <-- Auto-recovery watchdog script
└── saveshop-logs             <-- Interactive CLI log viewer & cleaner
```

---

## 4. Complete Step-by-Step Server Setup (Replication Guide)

Follow these exact steps in order when provisioning a fresh Ubuntu VPS from scratch:

### Step 1: Base System Update & Essential Tools
```bash
# Update package repositories and upgrade existing packages
apt update && apt upgrade -y

# Install required build tools, networking utilities, git, and logrotate
apt install -y curl wget git build-essential software-properties-common nginx ufw logrotate
```

### Step 2: Fix IPv6 DNS Resolution Delay (Critical for Google Auth & External APIs)
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

# Create dedicated database and application user
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
   ```
3. Apply connection & RAM protection tuning:
   ```bash
   cat << 'EOF' > /etc/postgresql/16/main/conf.d/saveshop-tuning.conf
   # Kill any transaction abandoned/idle for more than 60 seconds (prevents connection & RAM leaks)
   idle_in_transaction_session_timeout = 60000
   # Prevent runaway queries from locking tables (30s max)
   statement_timeout = 30000
   # Fast detection of broken/dropped client TCP sockets
   tcp_keepalives_idle = 60
   tcp_keepalives_interval = 10
   tcp_keepalives_count = 3
   EOF
   chmod 644 /etc/postgresql/16/main/conf.d/saveshop-tuning.conf
   systemctl restart postgresql
   ```
4. **Connect in pgAdmin**:
   - In pgAdmin > Register Server > Connection tab: `Host: localhost`, `Port: 5432`, `Maintenance Database: saveshop_db`, `Username: saveshop_user`.
   - In the **SSH Tunnel** tab: `SSH Host: 148.113.9.217`, `Port: 20016`, `Username: root`, `Password: _hJYJKvJTnmzJvpk` (or SSH Key).

### Step 4: Python 3.12 & Backend Application Setup
```bash
# Install Python 3.12, venv, and PostgreSQL dev headers
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
# Create protected configuration directory
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

# Create persistent production frontend environment record
cat << 'EOF' > /etc/saveshop/frontend.env
EXPO_PUBLIC_API_URL=https://chamber-golf-guardian-thumbnails.trycloudflare.com
EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID=898498745806-g40fimuhq99o7aohltn4qqinpvog31d5.apps.googleusercontent.com
EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID=898498745806-gnrm36ifk3qoek9et2ej5o6ajrrc1bbm.apps.googleusercontent.com
EOF
chmod 600 /etc/saveshop/frontend.env

# Symlink .env in the backend folder
ln -sf /etc/saveshop/backend.env /var/www/save-shop-backend/.env
```

### Step 6: Initialize Database Tables & Seed Primary Store
> [!IMPORTANT]
> A newly initialized database has 0 stores. Because the application requires an active store context to serve inventory, billing, and dashboard endpoints, you must seed an initial store and assign it to the admin user:

```bash
cd /var/www/save-shop-backend
./venv/bin/python -c "
from app.core.database import SessionLocal, init_db
from app.models.store import Store
import uuid

# 1. Initialize tables & migrations automatically
init_db()

# 2. Seed primary store if empty
db = SessionLocal()
if db.query(Store).count() == 0:
    store = Store(
        store_id=uuid.UUID('beda5c97-562e-4634-b921-b5f66b4c129c'),
        name='Save Shop Main Store',
        owner_name='Akash Bag',
        phone_number='9876543210',
        address='Main Road',
        state='19-West Bengal',
        email='akashbapibag9@gmail.com',
        is_active=True
    )
    db.add(store)
    db.commit()
    print('==> Seeded Initial Store:', store.store_id)
else:
    print('==> Store already exists in DB.')
db.close()
"
```

### Step 7: Create Backend Systemd Service with Persistent Logging
```bash
# Create dedicated logging directory
mkdir -p /var/log/saveshop
chmod 755 /var/log/saveshop

# Create backend systemd service file
cat << 'EOF' > /etc/systemd/system/save-shop-backend.service
[Unit]
Description=Save Shop Backend FastAPI Application
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/save-shop-backend
EnvironmentFile=/etc/saveshop/backend.env
ExecStart=/var/www/save-shop-backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2 --access-log
Restart=always
RestartSec=5
StandardOutput=append:/var/log/saveshop/backend.log
StandardError=append:/var/log/saveshop/backend-error.log

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd, enable and start service
systemctl daemon-reload
systemctl enable save-shop-backend
systemctl start save-shop-backend
```

### Step 8: Configure Nginx (Frontend SPA & API Reverse Proxy)
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

Enable site and restart Nginx:
```bash
mkdir -p /var/www/save-shop-frontend/dist
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/saveshop /etc/nginx/sites-enabled/saveshop
nginx -t
systemctl restart nginx
systemctl enable nginx
```

### Step 9: Install Cloudflare Tunnel (`cloudflared`)
```bash
# Download and install cloudflared
curl -L --output /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /usr/local/bin/cloudflared
```

### Step 10: Auto-Startup & Recovery Watchdog Setup
Create `/usr/local/bin/saveshop-startup.sh`:
```bash
cat << 'EOF' > /usr/local/bin/saveshop-startup.sh
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
EOF
chmod +x /usr/local/bin/saveshop-startup.sh
```

Create systemd watchdog service `/etc/systemd/system/saveshop-startup.service`:
```ini
[Unit]
Description=Save Shop Auto-Startup & Recovery Watchdog
After=network.target network-online.target postgresql.service nginx.service
Wants=network-online.target postgresql.service nginx.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/saveshop-startup.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Enable watchdog service and register crontab triggers:
```bash
systemctl daemon-reload
systemctl enable saveshop-startup.service

# Add crontab triggers for @reboot and every 5 minutes
(crontab -l 2>/dev/null; echo "*/5 * * * * /usr/local/bin/saveshop-startup.sh >/dev/null 2>&1"; echo "@reboot /usr/local/bin/saveshop-startup.sh >/dev/null 2>&1") | crontab -
```

### Step 11: Configure Automated Log Rotation & CLI Utility
1. Create `/etc/logrotate.d/saveshop`:
   ```bash
   cat << 'EOF' > /etc/logrotate.d/saveshop
   /var/log/saveshop/*.log {
       daily
       missingok
       rotate 7
       compress
       delaycompress
       notifempty
       copytruncate
   }
   EOF
   chmod 644 /etc/logrotate.d/saveshop
   ```
2. Install `saveshop-logs` utility at `/usr/local/bin/saveshop-logs`:
   ```bash
   cat << 'EOF' > /usr/local/bin/saveshop-logs
   #!/usr/bin/env bash
   LOG_DIR="/var/log/saveshop"
   BACKEND_LOG="$LOG_DIR/backend.log"
   BACKEND_ERR="$LOG_DIR/backend-error.log"
   STARTUP_LOG="/var/log/saveshop-startup.log"
   NGINX_ACCESS="/var/log/nginx/access.log"
   NGINX_ERR="/var/log/nginx/error.log"

   case "$1" in
       error|err)
           echo "=== Latest 50 Backend Errors ($BACKEND_ERR) ==="
           tail -n 50 "$BACKEND_ERR" 2>/dev/null || echo "No error log yet."
           ;;
       nginx)
           echo "=== Following Nginx Access & Error Logs (Ctrl+C to stop) ==="
           tail -f "$NGINX_ACCESS" "$NGINX_ERR"
           ;;
       startup)
           echo "=== Auto-Startup & Recovery Watchdog Log ($STARTUP_LOG) ==="
           tail -n 40 "$STARTUP_LOG" 2>/dev/null || echo "No startup log yet."
           ;;
       status|size)
           echo "=== Save Shop Log Files & Sizes ==="
           ls -lh "$LOG_DIR"/ "$STARTUP_LOG" "$NGINX_ACCESS" "$NGINX_ERR" 2>/dev/null
           ;;
       clean|clear)
           echo "=== Truncating / Cleaning Log Files ==="
           truncate -s 0 "$BACKEND_LOG" 2>/dev/null
           truncate -s 0 "$BACKEND_ERR" 2>/dev/null
           truncate -s 0 "$STARTUP_LOG" 2>/dev/null
           truncate -s 0 "$NGINX_ACCESS" 2>/dev/null
           truncate -s 0 "$NGINX_ERR" 2>/dev/null
           echo "Logs truncated successfully to 0 bytes. Disk space freed."
           ls -lh "$LOG_DIR"/ "$STARTUP_LOG"
           ;;
       help|--help|-h)
           echo "Usage: saveshop-logs [command]"
           echo "  (no args) : Follow live backend application logs (realtime)"
           echo "  error     : View latest 50 backend error stacktraces"
           echo "  nginx     : Follow live Nginx requests and error logs"
           echo "  startup   : View auto-recovery watchdog logs"
           echo "  size      : Check disk space used by all log files"
           echo "  clean     : Safely truncate all logs to 0 bytes"
           ;;
       *)
           echo "=== Following Live Backend Logs ($BACKEND_LOG) [Ctrl+C to stop] ==="
           touch "$BACKEND_LOG"
           tail -f "$BACKEND_LOG"
           ;;
   esac
   EOF
   chmod 755 /usr/local/bin/saveshop-logs
   ```

### Step 12: GitHub Actions Automated CI/CD Key Generation & Secrets Setup
To allow GitHub Actions to automatically run tests, build static web assets, and deploy via SSH/SCP:

1. **Generate SSH Keypair**:
   On your local machine (or the VPS), generate an ed25519 keypair:
   ```bash
   ssh-keygen -t ed25519 -C "github-actions-deploy" -f github_deploy_key
   ```
2. **Authorize Key on VPS**:
   ```bash
   mkdir -p /root/.ssh && chmod 700 /root/.ssh
   cat github_deploy_key.pub >> /root/.ssh/authorized_keys
   chmod 600 /root/.ssh/authorized_keys
   ```
3. **Configure Secrets in GitHub**:
   - In **Save-shop-backend** (`Settings > Secrets and variables > Actions`):
     - `VPS_HOST`: `148.113.9.217`
     - `VPS_PORT`: `20016`
     - `VPS_USER`: `root`
     - `VPS_SSH_KEY`: Content of `github_deploy_key` (private key)
   - In **Save-shop** (`Settings > Secrets and variables > Actions`):
     - `VPS_HOST`: `148.113.9.217`
     - `VPS_PORT`: `20016`
     - `VPS_USER`: `root`
     - `VPS_SSH_KEY`: Content of `github_deploy_key` (private key)
     - `EXPO_PUBLIC_API_URL`: `https://chamber-golf-guardian-thumbnails.trycloudflare.com` (or your domain)
     - `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID`: `898498745806-g40fimuhq99o7aohltn4qqinpvog31d5.apps.googleusercontent.com`
     - `EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID`: `898498745806-gnrm36ifk3qoek9et2ej5o6ajrrc1bbm.apps.googleusercontent.com`

### Step 13: Google Cloud OAuth 2.0 Credentials Setup
In your [Google Cloud Console](https://console.cloud.google.com/apis/credentials):
1. Open your OAuth 2.0 Web Client ID.
2. Under **Authorized JavaScript Origins**, add:
   - `https://chamber-golf-guardian-thumbnails.trycloudflare.com` (or your permanent domain)
   - `http://localhost:8081` (for local development)
3. Under **Authorized Redirect URIs**, add:
   - `https://chamber-golf-guardian-thumbnails.trycloudflare.com/`
   - `https://auth.expo.io/@akashbapibag/save-shop`

### Step 14: Swap Memory Configuration (LXC Container vs KVM VPS)
- **On Proxmox / OpenVZ LXC Containers** (like this VPS):
  The Linux kernel disables `swapon` inside unprivileged containers (`Operation not permitted`). The hosting provider or Proxmox host automatically assigns virtual swap (512MB active on this host).
- **On Standard KVM / Dedicated VPS** (DigitalOcean, AWS, Linode, Hetzner):
  Create a 2GB swap file:
  ```bash
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
  ```

### Step 15: Firewall Security (UFW) Configuration
If you enable UFW firewall, **always allow your mapped SSH port first**:
```bash
# Allow mapped SSH port
ufw allow 20016/tcp
# Allow HTTP and HTTPS
ufw allow 80/tcp
ufw allow 443/tcp
# Enable firewall safely
ufw enable
```

### Step 16: Upgrading from Quick Tunnel to Permanent Custom Domain
When you purchase a custom domain (e.g. `api.saveshop.com`):
- **Option A (If public ports 80/443 are directly routed to the VPS)**:
  Point your domain DNS A record to your VPS IP, then run:
  ```bash
  apt install -y certbot python3-certbot-nginx
  certbot --nginx -d yourdomain.com
  ```
- **Option B (If still behind NAT / closed ports 80/443)**:
  Use Cloudflare Named Tunnel:
  ```bash
  cloudflared tunnel login
  cloudflared tunnel create saveshop-prod
  cloudflared tunnel route dns saveshop-prod yourdomain.com
  # Configure /etc/cloudflared/config.yml to proxy to http://127.0.0.1:80
  cloudflared service install
  ```

---

## 5. Server Logging, Real-Time Debugging & Safe Log Cleanup

### Using `saveshop-logs`
```bash
# Follow live requests in real time:
saveshop-logs

# View latest 50 error stack traces:
saveshop-logs error

# View Nginx access & error traffic:
saveshop-logs nginx

# Check log sizes:
saveshop-logs size

# Safely truncate all logs to 0 bytes:
saveshop-logs clean
```

### Manual Log Inspection
```bash
# Tail live backend log
tail -f /var/log/saveshop/backend.log

# Search for 500 errors in backend
grep " 500 " /var/log/saveshop/backend.log

# View last 100 lines of error log
tail -n 100 /var/log/saveshop/backend-error.log

# View live Nginx requests
tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

---

## 6. Crash & Emergency Management Commands

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
