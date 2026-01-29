# UniFi API Reference

## API Types

UniFi offers two API access methods:

### 1. Local Controller API (Recommended for Homelab)
Direct access to your UniFi Controller/UDM with full read/write capabilities.

### 2. Cloud API (Read-Only)
Centralized cloud management via api.ui.com (read-only, 10k requests/min).

---

## Local Controller API

### Base URLs

**Standard Controller:**
```
https://{controller-ip}:8443/api
```

**UDM/UDM Pro/UCG Devices:**
```
https://{udm-ip}/proxy/network/api
```

Default port: `8443` (or `443` for UDM)

### Authentication

Session-based with cookies.

**Session Caching:** Sessions are automatically cached to `~/.cache/homelab/unifi_session_<host>.pkl` with 1.5h lifetime. This prevents rate-limiting and improves performance (~55% faster). Network and Protect APIs share the same session.

#### 1. Login

**Endpoint:** `POST /api/login` (or `/api/auth/login` for UDM)

**Request:**
```json
{
  "username": "admin",
  "password": "your-password"
}
```

**Response:**
Returns session cookies (`unifises`, `TOKEN`) and CSRF token.

#### 2. Using Session

Include cookies in subsequent requests:
```
Cookie: unifises=xxx; TOKEN=yyy
```

For POST/PUT/DELETE, also include:
```
X-CSRF-Token: your-csrf-token
```

#### 3. Logout

**Endpoint:** `POST /api/logout`

### Common Endpoints

Replace `{site}` with site name (usually `default`).

#### Clients

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/stat/sta` | Active client devices |
| GET | `/api/s/{site}/rest/user` | All known clients |
| POST | `/api/s/{site}/cmd/stamgr` | Client actions (kick, block) |

**Kick client:**
```json
{
  "cmd": "kick-sta",
  "mac": "aa:bb:cc:dd:ee:ff"
}
```

**Block client:**
```json
{
  "cmd": "block-sta",
  "mac": "aa:bb:cc:dd:ee:ff"
}
```

#### Devices

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/stat/device` | All devices |
| GET | `/api/s/{site}/stat/device/{mac}` | Specific device |
| POST | `/api/s/{site}/cmd/devmgr` | Device actions |

**Restart device:**
```json
{
  "cmd": "restart",
  "mac": "aa:bb:cc:dd:ee:ff"
}
```

**Adopt device:**
```json
{
  "cmd": "adopt",
  "mac": "aa:bb:cc:dd:ee:ff"
}
```

#### Networks

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/rest/networkconf` | All networks |
| GET | `/api/s/{site}/rest/wlanconf` | WiFi networks |
| POST | `/api/s/{site}/rest/wlanconf` | Create WiFi network |
| PUT | `/api/s/{site}/rest/wlanconf/{id}` | Update WiFi network |

#### Statistics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/stat/health` | Site health |
| GET | `/api/s/{site}/stat/sysinfo` | System info |
| GET | `/api/s/{site}/stat/sitedpi` | DPI statistics |
| GET | `/api/s/{site}/stat/event` | Recent events |

#### Port Forwarding

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/rest/portforward` | List rules |
| POST | `/api/s/{site}/rest/portforward` | Create rule |
| PUT | `/api/s/{site}/rest/portforward/{id}` | Update rule |
| DELETE | `/api/s/{site}/rest/portforward/{id}` | Delete rule |

#### Firewall

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/rest/firewallrule` | List firewall rules |
| GET | `/api/s/{site}/rest/firewallgroup` | List firewall groups (IP/port groups) |
| POST | `/api/s/{site}/rest/firewallrule` | Create firewall rule |
| PUT | `/api/s/{site}/rest/firewallrule/{id}` | Update firewall rule |
| DELETE | `/api/s/{site}/rest/firewallrule/{id}` | Delete firewall rule |

#### System (UDM Only)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/system/reboot` | Reboot UDM |
| POST | `/api/system/poweroff` | Power off UDM |
| GET | `/api/system/backup` | List backups |

### Response Format

```json
{
  "meta": {
    "rc": "ok"
  },
  "data": [...]
}
```

Error response:
```json
{
  "meta": {
    "rc": "error",
    "msg": "error message"
  }
}
```

---

## Cloud API (api.ui.com)

### Authentication

API Key in header:
```
X-API-KEY: your-api-key
```

**Create API Key:**
1. Login to unifi.ui.com
2. GA → API section or EA → Settings → API Keys
3. Create New API Key
4. Save key (shown once)

### Base URL

```
https://api.ui.com/v1
```

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/hosts` | List hosts |
| GET | `/hosts/{id}` | Get host by ID |
| GET | `/sites` | List sites |
| GET | `/devices` | List devices |
| GET | `/isp/metrics` | ISP metrics |

### Rate Limits

- Early Access: 100 requests/min
- Stable v1: 10,000 requests/min

### Note

Cloud API is currently **read-only**. Use local API for write operations.

---

## Error Handling

HTTP status codes:
- `200` - Success
- `400` - Bad request
- `401` - Unauthorized (invalid credentials/session)
- `403` - Forbidden (insufficient permissions)
- `404` - Not found
- `429` - Rate limit exceeded
- `500` - Server error

## SSL Certificates

Most UniFi Controllers use self-signed certificates. Disable SSL verification for local access:
```python
requests.get(url, verify=False)
```

Or add certificate to trust store.

## Sources

- [UniFi Controller API Community Wiki](https://ubntwiki.com/products/software/unifi-controller/api)
- [Official UniFi API Documentation](https://developer.ui.com/site-manager-api/gettingstarted)
- [UniFi Network API](https://developer.ui.com/network/v10.1.68/gettingstarted)
