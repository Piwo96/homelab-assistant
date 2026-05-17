# Network Topology

The home network has TWO routers cascaded — this is non-obvious and was a major source of confusion in the original rolly deploy. Internalize this diagram before debugging any "connection timed out" issue.

## The Two-Router Cascade

```
Internet (Telegram, Let's Encrypt, etc.)
    │
    │  public IPv4 (dynamic, currently 87.156.30.x)
    ▼
┌──────────────────────────────────────────────────────────────────┐
│ FritzBox @ 192.168.178.1                                         │
│  - DSL uplink                                                    │
│  - DuckDNS auto-update of sophia-und-philipp.duckdns.org         │
│  - "Exposed Host" set to 192.168.178.20                          │
│    → forwards ALL inbound traffic blindly to that IP             │
│  - No per-port forwards needed here                              │
│  - Subnet: 192.168.178.0/24                                      │
└────────────────────────────┬─────────────────────────────────────┘
                             │  inbound = forwarded; outbound = NAT
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ UniFi Gateway @ 192.168.178.20 (WAN) / 192.168.10.1 (LAN VLAN)   │
│  - VLAN router for multiple subnets, including 192.168.10.0/24   │
│  - Has its OWN port-forward rules (managed by unifi-network      │
│    skill via API or web UI at unifi.local)                       │
│  - This is where per-app forwards live: 8443 → 192.168.10.200    │
└────────────────────────────┬─────────────────────────────────────┘
                             │  cross-VLAN routing
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ Proxmox host @ 192.168.10.140                                    │
│  - vmbr0 bridge to 192.168.10.0/24                               │
│  - LXC containers get static IPs in this range                   │
└────────────────────────────┬─────────────────────────────────────┘
                             │  bridged
                             ▼
   Your app's LXC @ 192.168.10.200
```

## Implications

1. **For a public-facing app to be reachable from the internet:**
   - FritzBox needs nothing extra (Exposed Host already punts everything to UniFi).
   - **UniFi needs a port-forward rule** for the app's port → the LXC's static IP.
   - Manage via `python3 .claude/skills/unifi-network/scripts/network_api.py port-forwards` (list) / `create-port-forward` / `delete-port-forward`.

2. **Cross-subnet routing** (192.168.10.x → 192.168.1.x or similar):
   - Goes through the UniFi gateway, NOT directly via FritzBox.
   - Verify with `ping`/`curl` from inside the LXC.
   - LM Studio at 192.168.1.135:1234 is reachable from the LXC via this route.

3. **Outbound restrictions:**
   - **Port 53 to arbitrary IPs is BLOCKED** by FritzBox. This breaks Caddy's DNS-01 propagation self-check (it tries to dial authoritative nameservers directly). Fix: `propagation_timeout -1` in the Caddy tls block. The DuckDNS API call already confirmed the TXT record.
   - Port 443 outbound works fine (proven by `curl https://www.duckdns.org/update?...` returning `OK` from inside the LXC).

4. **Hairpin NAT is off (or unreliable):**
   - From the Mac (on 192.168.x), curl-ing the FritzBox's public IP+port DOES NOT loop back to the internal LAN.
   - Symptom: `curl https://sophia-und-philipp.duckdns.org:8443/health` from the Mac times out, but Telegram (from the actual internet) reaches it fine.
   - Don't waste time debugging this from inside the LAN — test from cellular data or trust that Telegram's `getWebhookInfo` reports no errors.

## Verifying Topology Live

```bash
# From the Mac:
ssh root@192.168.10.140 'ip a'        # Proxmox host NICs + bridge
ssh root@192.168.10.140 'ip route'    # Default route via UniFi

# From a deployed LXC:
ssh root@192.168.10.200 \
  'ip route; curl -fsS http://192.168.1.135:1234/v1/models | head -3'

# UniFi current forwards:
python3 .claude/skills/unifi-network/scripts/network_api.py port-forwards

# FritzBox public IP (sanity-check DuckDNS update is fresh):
curl https://api.ipify.org
dig +short sophia-und-philipp.duckdns.org @8.8.8.8
# Both should match.
```

## Diagnostic Flow for "Telegram says timeout"

1. From the LXC: `curl -fsS http://127.0.0.1:<port>/health` — proves the bot itself works.
2. From the LXC: `curl -fsSk https://127.0.0.1:<public_port>/health` — proves Caddy + cert is up.
3. From the Mac: `curl -fsS --resolve <duckdns_host>:<port>:192.168.10.<lxc> https://<duckdns_host>:<port>/health` — proves the cert chain end-to-end (bypasses the routers).
4. `python3 .claude/skills/unifi-network/scripts/network_api.py port-forwards` — verify the forward exists AND points at the right internal IP. A stale rule pointing at an old/deleted LXC IP is the #1 cause of "connection timed out" from external clients.
5. `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo` — `last_error_message` is authoritative for what Telegram sees.

If step 3 succeeds but step 5 still errors, the issue is either:
- Stale UniFi forward (step 4)
- FritzBox Exposed Host pointing at the wrong device
- Recent public-IP change that DuckDNS hasn't propagated yet (`dig` should match `ipify`)
