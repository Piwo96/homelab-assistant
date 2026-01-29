# UniFi API Reference

> **Version 2.0.0**: Migrated from Legacy-only to Dual-API architecture (Integration API v1 primary + Legacy fallback). See [SKILL.md](SKILL.md) Architecture Notes for design rationale.

## API Modes

This skill supports two API access methods that can be used independently or together:

| Mode | Auth | Base URL | Features |
|------|------|----------|----------|
| **Integration API v1** (Primary) | API Key | `https://{host}/proxy/network/integration/v1` | Pagination, filtering, device stats, CRUD |
| **Legacy API** (Fallback) | Session cookies | `https://{host}/proxy/network/api` | Kick/block, health, DPI, port forwarding, firewall |

---

## Integration API v1 (Primary)

Official REST API with pagination, filtering, and UUID-based identifiers.

### Authentication

API Key in header:
```
X-API-Key: your-api-key
```

**Create API Key:**
1. Log into UniFi web UI
2. Settings → API → Create New API Key
3. Save key (shown once)
4. Add to `.env`: `UNIFI_API_KEY=your-key`

No session management needed. No cookies, no CSRF tokens.

### Base URL

```
https://{host}/proxy/network/integration/v1
```

### Pagination

All list endpoints return paginated responses:

```json
{
  "offset": 0,
  "limit": 50,
  "count": 10,
  "totalCount": 42,
  "data": [...]
}
```

Query parameters: `?offset=0&limit=50`

### Filtering

List endpoints support structured filtering via `?filter=` parameter:

**Property expressions:** `name.eq('MyDevice')`, `state.eq('ONLINE')`
**Compound expressions:** `and(name.isNotNull(), state.eq('ONLINE'))`
**Negation:** `not(name.like('guest*'))`

**Functions:** `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `like`, `in`, `notIn`, `isNull`, `isNotNull`, `isEmpty`, `contains`, `containsAny`, `containsAll`

**Pattern matching (like):** `.` = any single char, `*` = any chars, `\` = escape

### Endpoints

#### Info & Sites

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/info` | Application version |
| GET | `/v1/sites` | List all sites (UUID-based) |

#### Devices

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/sites/{siteId}/devices` | List adopted devices (paginated) |
| GET | `/v1/sites/{siteId}/devices/{deviceId}` | Device details |
| GET | `/v1/sites/{siteId}/devices/{deviceId}/statistics/latest` | Device stats (CPU, RAM, uptime) |
| POST | `/v1/sites/{siteId}/devices` | Adopt device `{"macAddress": "...", "ignoreDeviceLimit": false}` |
| POST | `/v1/sites/{siteId}/devices/{deviceId}/actions` | Device action `{"action": "RESTART"}` |
| POST | `/v1/sites/{siteId}/devices/{deviceId}/interfaces/ports/{portIdx}/actions` | Port action `{"action": "POWER_CYCLE"}` |
| GET | `/v1/pending-devices` | List pending devices (paginated) |

**Device response fields:** `id`, `macAddress`, `ipAddress`, `name`, `model`, `state` (ONLINE/OFFLINE), `supported`, `firmwareVersion`, `firmwareUpdatable`, `features` (switching, accessPoint, gateway), `interfaces` (ports, radios)

**Statistics fields:** `uptimeSec`, `cpuUtilizationPct`, `memoryUtilizationPct`, `loadAverage1Min/5Min/15Min`, `lastHeartbeatAt`, `uplink.txRateBps/rxRateBps`

#### Clients

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/sites/{siteId}/clients` | List connected clients (paginated) |
| GET | `/v1/sites/{siteId}/clients/{clientId}` | Client details |
| POST | `/v1/sites/{siteId}/clients/{clientId}/actions` | Client action |

**Client actions:**
- `{"action": "AUTHORIZE_GUEST_ACCESS", "timeLimitMinutes": 60, "dataUsageLimitMBytes": 500}`
- `{"action": "UNAUTHORIZE_GUEST_ACCESS"}`

**Client response fields:** `type` (WIRED/WIRELESS/VPN/TELEPORT), `id`, `name`, `connectedAt`, `ipAddress`, `macAddress`, `uplinkDeviceId`, `access` (DEFAULT/GUEST)

#### Networks

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/sites/{siteId}/networks` | List networks (paginated) |
| GET | `/v1/sites/{siteId}/networks/{networkId}` | Network details |
| POST | `/v1/sites/{siteId}/networks` | Create network |
| PUT | `/v1/sites/{siteId}/networks/{networkId}` | Update network |
| DELETE | `/v1/sites/{siteId}/networks/{networkId}` | Delete network |
| GET | `/v1/sites/{siteId}/networks/{networkId}/references` | Network references |

**Create/Update body:**
```json
{
  "management": "GATEWAY",
  "name": "IoT Network",
  "enabled": true,
  "vlanId": 30,
  "isolationEnabled": false,
  "internetAccessEnabled": true,
  "mdnsForwardingEnabled": false,
  "dhcpGuarding": { "trustedDhcpServerIpAddresses": ["192.168.1.1"] }
}
```

**Management types:** `GATEWAY`, `SWITCH`, `UNMANAGED`

#### WiFi Broadcasts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/sites/{siteId}/wifi/broadcasts` | List WiFi broadcasts (paginated) |
| GET | `/v1/sites/{siteId}/wifi/broadcasts/{id}` | WiFi details |
| POST | `/v1/sites/{siteId}/wifi/broadcasts` | Create WiFi broadcast |
| PUT | `/v1/sites/{siteId}/wifi/broadcasts/{id}` | Update WiFi broadcast |
| DELETE | `/v1/sites/{siteId}/wifi/broadcasts/{id}` | Delete WiFi broadcast |

**Create/Update body:**
```json
{
  "type": "STANDARD",
  "name": "Guest WiFi",
  "enabled": true,
  "securityConfiguration": { "type": "WPA2" },
  "multicastToUnicastConversionEnabled": true,
  "clientIsolationEnabled": false,
  "hideName": false,
  "uapsdEnabled": true
}
```

**WiFi types:** `STANDARD`, `IOT_OPTIMIZED`

### Error Response

```json
{
  "statusCode": 400,
  "statusName": "BAD_REQUEST",
  "code": "api.error.code",
  "message": "Human-readable error message",
  "timestamp": "2025-01-29T12:00:00Z",
  "requestPath": "/integration/v1/sites/...",
  "requestId": "uuid"
}
```

### Cloud Connector API

For remote access via api.ui.com (requires firmware >= 5.0.3):

```
https://api.ui.com/v1/connector/consoles/{hostId}/network/integration/v1/...
```

Supports all HTTP methods (GET, POST, PUT, DELETE, PATCH) proxied to the local console.

---

## Legacy API (Fallback)

Unofficial community-documented API. Used for features not available in Integration API v1.

### Authentication

Session-based with cookies.

**Session Caching:** Sessions cached to `~/.cache/homelab/unifi_session_<host>.pkl` with 1.5h lifetime. Network and Protect APIs share the same session.

#### Login

**UDM/UCG:** `POST https://{host}/api/auth/login`
**Standard Controller:** `POST https://{host}:8443/api/login`

```json
{
  "username": "admin",
  "password": "your-password"
}
```

Returns session cookies (`unifises`, `TOKEN`) and CSRF token.

### Base URLs

**UDM/UCG:** `https://{host}/proxy/network/api`
**Standard Controller:** `https://{host}:8443/api`

### Endpoints

Replace `{site}` with site name (usually `default`).

#### Clients

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/stat/sta` | Active client devices |
| GET | `/api/s/{site}/rest/user` | All known clients |
| POST | `/api/s/{site}/cmd/stamgr` | Client actions (kick, block, unblock) |

**Kick:** `{"cmd": "kick-sta", "mac": "aa:bb:cc:dd:ee:ff"}`
**Block:** `{"cmd": "block-sta", "mac": "aa:bb:cc:dd:ee:ff"}`
**Unblock:** `{"cmd": "unblock-sta", "mac": "aa:bb:cc:dd:ee:ff"}`

#### Devices

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/stat/device` | All devices |
| POST | `/api/s/{site}/cmd/devmgr` | Device actions (restart, adopt) |

**Restart:** `{"cmd": "restart", "mac": "aa:bb:cc:dd:ee:ff"}`
**Adopt:** `{"cmd": "adopt", "mac": "aa:bb:cc:dd:ee:ff"}`

#### Networks & WiFi

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/rest/networkconf` | All networks |
| GET | `/api/s/{site}/rest/wlanconf` | WiFi networks |

#### Statistics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/stat/health` | Site health |
| GET | `/api/s/{site}/stat/sysinfo` | System info |
| GET | `/api/s/{site}/stat/sitedpi` | DPI statistics |

#### Port Forwarding

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/rest/portforward` | List rules |
| POST | `/api/s/{site}/rest/portforward` | Create rule |
| DELETE | `/api/s/{site}/rest/portforward/{id}` | Delete rule |

#### Firewall

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/s/{site}/rest/firewallrule` | List firewall rules |
| GET | `/api/s/{site}/rest/firewallgroup` | List firewall groups |

### Response Format

```json
{
  "meta": { "rc": "ok" },
  "data": [...]
}
```

---

## Error Handling

HTTP status codes (both APIs):
- `200` - Success
- `400` - Bad request
- `401` - Unauthorized (invalid credentials/session/API key)
- `403` - Forbidden (insufficient permissions)
- `404` - Not found
- `408` - Request timeout
- `429` - Rate limit exceeded
- `500` - Server error
- `502` - Bad gateway (console unreachable)

## SSL Certificates

Most UniFi Controllers use self-signed certificates. Set `UNIFI_VERIFY_SSL=false` in `.env`.

## Sources

- [UniFi Network Integration API](https://developer.ui.com/network)
- [UniFi Site Manager API](https://developer.ui.com/site-manager-api/gettingstarted)
- [UniFi Controller API Community Wiki](https://ubntwiki.com/products/software/unifi-controller/api)
