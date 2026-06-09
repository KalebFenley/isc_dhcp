# isc_dhcp

Renders a complete ISC DHCP server config (`dhcpd.conf`) from VLAN definitions and subnet CIDRs using a Jinja2 template.

## How it works

You provide a YAML file with global server settings, VLAN IDs, and subnet CIDRs. The script derives the addressing for each subnet automatically:

| Field | Default assignment |
|---|---|
| Gateway | First host (`.1`) — overridable per subnet |
| Reserved at start | 3 hosts (gateway + 2 VRRP peers) — configurable |
| DHCP range start | First host after the start reservation (`.4`) |
| DHCP range end | Last host, minus any end reservation |

Subnets are checked for overlaps across all VLANs at render time.

## Requirements

```bash
pip install -r requirements.txt
```

## Usage

```bash
python3 render.py [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `-t`, `--template` | `dhcp.j2` | Jinja2 template file |
| `-i`, `--input` | `vars.yaml` | YAML input file |
| `-o`, `--output` | stdout | Output file path |

### Examples

```bash
# Render to stdout
python3 render.py

# Custom input/template
python3 render.py -i my_vlans.yaml -t my_template.j2

# Write to file
python3 render.py -o dhcpd.conf
```

Copy `vars.yaml.example` as a starting point: `cp vars.yaml.example vars.yaml` (`vars.yaml` is gitignored so real site data stays out of the repo).

## Input format

```yaml
global:
  parameters:                  # bare statements: <name> <value>;
    authoritative: true        # true -> "authoritative;", false -> "not authoritative;"
    ddns-update-style: none
    default-lease-time: 86400
    max-lease-time: 604800
  options:                     # option statements: option <name> <value>;
    domain-name-servers: [8.8.8.8, 1.1.1.1]
    domain-name: example.local
  raw: |                       # literal lines passed through verbatim
    option space acs;
    option acs.url code 1 = text;
    vendor-option-space acs;
    option acs.url "https://acs.example.local:7547/";

defaults:                      # per-subnet settings (all optional)
  reserved_at_start: 3         # hosts excluded before the range
  reserved_at_end: 0           # hosts excluded at the top of the range
  log_requests: false          # log() every request handled in the subnet

vlans:
  - id: 10
    description: servers
    subnets:
      - 192.168.10.0/24        # plain CIDR uses the defaults
  - id: 20
    reserved_at_start: 10      # VLAN-level override
    subnets:
      - cidr: 10.20.0.0/23     # dict form for per-subnet overrides
        gateway: 10.20.1.254
        reserved_at_end: 20
```

### Value formatting rules

- **`parameters`** values are emitted verbatim — include quotes yourself where dhcpd requires them (e.g. `filename: '"pxelinux.0"'`).
- **`options`** values are formatted automatically: lists are comma-joined, strings are quoted unless they parse as an IP address, numbers pass through as-is.
- **`raw`** is the escape hatch for anything the above can't express: custom option spaces (e.g. TR-069 ACS URLs), failover peers, hex option data, conditionals.

### Setting precedence

`reserved_at_start`, `reserved_at_end`, and `log_requests` cascade: subnet ➜ VLAN ➜ `defaults` ➜ built-in default.

## Validating the output

If `dhcpd` is installed, syntax-check a rendered config without touching a running server:

```bash
dhcpd -t -cf dhcpd.conf
```

The test suite runs this check automatically when `dhcpd` is available:

```bash
python3 -m pytest tests/
```

## Files

| File | Description |
|---|---|
| `render.py` | Main script |
| `dhcp.j2` | Jinja2 template for the full dhcpd.conf |
| `vars.yaml.example` | Example input structure |
| `tests/` | pytest suite |
| `requirements.txt` | Python dependencies |
