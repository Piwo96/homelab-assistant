# Proxmox VE API Reference

## Authentication

### API Token (Recommended)
No CSRF token needed. Tokens can be revoked without disabling user.

**Header format:**
```
Authorization: PVEAPIToken=USER@REALM!TOKENID=UUID
```

**Example:**
```bash
curl -H "Authorization: PVEAPIToken=root@pam!homelab=abc-123-def" \
  https://192.168.10.140:8006/api2/json/nodes
```

### Creating an API Token
1. Datacenter → Permissions → API Tokens
2. Add: User `root@pam`, Token ID `homelab`
3. Uncheck "Privilege Separation" for full access
4. Save the UUID (shown only once)

## Base URL

```
https://{PROXMOX_HOST}:{PROXMOX_PORT}/api2/json
```

Default port: `8006`

## Endpoints

### Nodes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/nodes` | List all cluster nodes |
| GET | `/nodes/{node}/status` | Node status (CPU, RAM, uptime) |

### Virtual Machines (QEMU)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/nodes/{node}/qemu` | List all VMs |
| GET | `/nodes/{node}/qemu/{vmid}/status/current` | VM status |
| POST | `/nodes/{node}/qemu/{vmid}/status/start` | Start VM |
| POST | `/nodes/{node}/qemu/{vmid}/status/stop` | Stop VM (hard) |
| POST | `/nodes/{node}/qemu/{vmid}/status/shutdown` | Shutdown VM (graceful) |
| POST | `/nodes/{node}/qemu/{vmid}/status/reboot` | Reboot VM |
| GET | `/nodes/{node}/qemu/{vmid}/config` | VM configuration |

### Containers (LXC)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/nodes/{node}/lxc` | List all containers |
| GET | `/nodes/{node}/lxc/{vmid}/status/current` | Container status |
| POST | `/nodes/{node}/lxc/{vmid}/status/start` | Start container |
| POST | `/nodes/{node}/lxc/{vmid}/status/stop` | Stop container |
| POST | `/nodes/{node}/lxc/{vmid}/status/shutdown` | Shutdown container |
| GET | `/nodes/{node}/lxc/{vmid}/config` | Container config (includes mounts) |
| PUT | `/nodes/{node}/lxc/{vmid}/config` | Update container config |

### Storage

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/storage` | List all cluster storage |
| GET | `/nodes/{node}/storage` | List storage on node |
| GET | `/nodes/{node}/storage/{storage}/status` | Storage status |
| GET | `/nodes/{node}/storage/{storage}/content` | Storage content |

## LXC Mount Points

Add bind mount to container:
```bash
PUT /nodes/{node}/lxc/{vmid}/config
Content-Type: application/x-www-form-urlencoded

mp0=/mnt/pve/qnap-share,mp=/data
```

Mount point format: `mp{N}={source},mp={target}[,ro={0|1}]`

## Response Format

All responses are JSON:
```json
{
  "data": [ ... ]  // or object for single resource
}
```

## Error Handling

HTTP status codes:
- `200` - Success
- `400` - Bad request (invalid parameters)
- `401` - Unauthorized (bad token)
- `403` - Forbidden (insufficient permissions)
- `500` - Server error

## SSL Certificate

For self-signed certificates, disable verification:
```python
requests.get(url, verify=False)
```

Or add CA to trust store for production use.
