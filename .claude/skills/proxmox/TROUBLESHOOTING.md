# Proxmox Troubleshooting

Known issues and solutions. This document grows through self-annealing - add new issues as they're discovered.

## Connection Issues

### SSL Certificate Error
```
requests.exceptions.SSLError: certificate verify failed
```
**Cause**: Self-signed certificate on Proxmox server.
**Solution**: Set `PROXMOX_VERIFY_SSL=false` in `.env`.

### Connection Refused
```
Error: Cannot connect to 192.168.10.140:8006
```
**Cause**: Wrong IP, port, or Proxmox not running.
**Solution**:
1. Verify IP: `ping $PROXMOX_HOST`
2. Check port: `nc -zv $PROXMOX_HOST 8006`
3. Verify pveproxy running: `systemctl status pveproxy` (on Proxmox node)

### Connection Timeout
```
requests.exceptions.ConnectTimeout
```
**Cause**: Network issue or firewall blocking.
**Solution**:
1. Check firewall rules on Proxmox
2. Verify VPN connection if applicable
3. Try from same network segment

## Authentication Issues

### 401 Unauthorized
```
Error: 401 - authentication failure
```
**Cause**: Invalid token credentials.
**Solution**:
1. Verify `PROXMOX_TOKEN_ID` format: `user@realm!tokenname`
2. Verify `PROXMOX_TOKEN_SECRET` is the UUID, not the token name
3. Check token hasn't expired in Datacenter → Permissions → API Tokens

### 403 Forbidden
```
Error: 403 - permission denied
```
**Cause**: Token lacks required permissions.
**Solution**:
1. In Proxmox web UI: Datacenter → Permissions → API Tokens
2. Edit the token
3. Uncheck "Privilege Separation" for full access
4. Or add specific permissions via Datacenter → Permissions → Add

## Operation Issues

### VM/Container Not Found
```
Error: 500 - VM 999 does not exist
```
**Cause**: Wrong VMID or wrong node.
**Solution**:
1. List all VMs: `proxmox_api.py vms <node>`
2. List all containers: `proxmox_api.py containers <node>`
3. Check correct node name

### Mount Not Visible After Adding
**Cause**: Container was running when mount was added.
**Solution**: Restart the container:
```bash
proxmox_api.py restart <node> <vmid>
```

### Snapshot Fails on Running VM
```
Error: 500 - guest agent is not running
```
**Cause**: QEMU guest agent not installed/running.
**Solution**:
1. Install guest agent in VM: `apt install qemu-guest-agent`
2. Enable in VM config: Options → QEMU Guest Agent → Enable
3. Start agent: `systemctl start qemu-guest-agent`

### Container Snapshot Treated as VM
**Cause**: Script defaults to QEMU (VM) type.
**Solution**: Use `--lxc` flag:
```bash
proxmox_api.py snapshot <node> <vmid> --name backup --lxc
```

### Node Name Not Found
```
Error: Node 'pve' not found in cluster
```
**Cause**: Node name mismatch (e.g., actual node is named 'pve-rollmann' not 'pve').
**Solution**: The script auto-detects the correct node name if you omit it or provide an invalid name. For most commands, you can simply omit the node parameter:
```bash
# Auto-detect node (recommended)
proxmox_api.py vms
proxmox_api.py start 100

# Or check actual node name first
proxmox_api.py nodes
```

Commands with auto-detection:
- `vms`, `containers`, `node-status`, `overview`
- `start`, `stop`, `shutdown`, `reboot`

## Performance Issues

### Slow API Responses
**Cause**: Large cluster or high load.
**Solution**:
1. Increase timeout in script if needed
2. Avoid bulk operations during peak usage
3. Check Proxmox node resources: `proxmox_api.py node-status <node>`

### Rate Limiting
**Cause**: Too many API requests in short time.
**Solution**: Add delays between bulk operations:
```python
import time
for vmid in vmids:
    api.vm_action(node, vmid, "start")
    time.sleep(1)  # 1 second delay
```

---

## Adding New Issues

When you encounter a new issue:

1. Document the error message exactly
2. Identify the root cause
3. Provide a clear solution
4. Add to appropriate section above

Format:
```markdown
### Issue Title
```
error message here
```
**Cause**: Why this happens.
**Solution**: How to fix it.
```
