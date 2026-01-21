# Pi-hole API Reference

## API Versions

Pi-hole v6+ uses a built-in REST API with self-hosted documentation.

**Local documentation:** `http://{PIHOLE_HOST}/api/docs`

## Authentication

### Session-Based Authentication

Pi-hole uses session IDs (SIDs) rather than static API tokens.

#### 1. Login to Get Session ID

```bash
curl -X POST http://pihole.local/api/auth \
  -H "Content-Type: application/json" \
  -d '{"password":"your-password"}'
```

**Response:**
```json
{
  "session": {
    "sid": "vFA+EP4MQ5JJvJg+3Q2Jnw==",
    "validity": 300,
    "csrf": "token-here"
  }
}
```

#### 2. Use Session ID in Requests

Four ways to pass SID:
- **Header** (recommended): `X-FTL-SID: vFA+EP4MQ5JJvJg+3Q2Jnw==`
- **Query param**: `?sid=vFA+EP4MQ5JJvJg+3Q2Jnw==`
- **Cookie**: `sid=vFA+EP4MQ5JJvJg+3Q2Jnw==` (requires `X-FTL-CSRF` header)
- **JSON body**: `{"sid":"vFA+EP4MQ5JJvJg+3Q2Jnw=="}`

#### 3. Logout

```bash
curl -X DELETE http://pihole.local/api/auth \
  -H "X-FTL-SID: your-sid"
```

### Application Passwords

For automation, generate application passwords in:
Web Interface → Settings → API / Web interface

## Common Endpoints

### Statistics

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/stats/summary` | Summary statistics | No |
| GET | `/api/stats/overTime/clients` | Clients over time | No |
| GET | `/api/stats/overTime/history` | Query history | No |
| GET | `/api/stats/top_domains` | Top blocked/permitted domains | Yes |
| GET | `/api/stats/top_clients` | Top clients | Yes |
| GET | `/api/stats/query_types` | Query type distribution | No |
| GET | `/api/stats/upstreams` | Upstream server stats | No |

### DNS Blocking

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/dns/blocking` | Get blocking status | No |
| POST | `/api/dns/blocking` | Enable/disable blocking | Yes |

**Enable blocking:**
```json
{"blocking": true}
```

**Disable for duration:**
```json
{"blocking": false, "timer": 300}
```

### Queries

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/queries` | Recent queries | Yes |
| GET | `/api/queries?domain=example.com` | Filter by domain | Yes |
| GET | `/api/queries?client=192.168.1.100` | Filter by client | Yes |

### Blocklists

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/lists` | All lists (allowlist, blocklist) | Yes |
| POST | `/api/lists` | Add new list | Yes |
| PUT | `/api/lists/{id}` | Update list | Yes |
| DELETE | `/api/lists/{id}` | Remove list | Yes |
| POST | `/api/gravity` | Update gravity (pull lists) | Yes |

### Domains (Custom Lists)

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/domains` | Get custom domains | Yes |
| POST | `/api/domains` | Add domain to list | Yes |
| DELETE | `/api/domains/{id}` | Remove domain | Yes |

**Add to blocklist:**
```json
{
  "domain": "ads.example.com",
  "kind": "block",
  "comment": "Blocked via API"
}
```

**Add to allowlist:**
```json
{
  "domain": "safe.example.com",
  "kind": "allow"
}
```

### System

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/info` | Pi-hole version and system info | No |
| GET | `/api/dns/status` | DNS service status | No |
| POST | `/api/system/reboot` | Reboot system | Yes |
| POST | `/api/system/restart` | Restart Pi-hole services | Yes |

## Response Format

All responses are JSON:
```json
{
  "took": 0.123,  // Request processing time
  "data": { ... } // or array
}
```

## Error Handling

HTTP status codes:
- `200` - Success
- `400` - Bad request (invalid parameters)
- `401` - Unauthorized (no/invalid SID)
- `403` - Forbidden (insufficient permissions)
- `429` - Too many requests (rate limit)
- `500` - Server error

## Legacy API (Pre-v6)

If using Pi-hole v5 or older:

```bash
# Summary
curl "http://pihole.local/admin/api.php?summary"

# Enable/Disable (requires token)
curl "http://pihole.local/admin/api.php?disable=300&auth=your-api-token"
curl "http://pihole.local/admin/api.php?enable&auth=your-api-token"

# Top items
curl "http://pihole.local/admin/api.php?topItems=10&auth=your-api-token"
```

Token location: `/etc/pihole/setupVars.conf` → `WEBPASSWORD`

## Sources

- [Pi-hole API Documentation](https://docs.pi-hole.net/api/)
- [Authentication Guide](https://docs.pi-hole.net/api/auth/)
