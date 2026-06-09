# isc_dhcp

Renders ISC DHCP server configs from VLAN definitions and subnet CIDRs using a Jinja2 template.

## How it works

You provide a YAML file with VLAN IDs and subnet CIDRs. The script automatically derives all DHCP fields from each CIDR:

| Field | Assignment |
|---|---|
| Gateway | First host (`.1`) |
| VRRP peer 1 | Second host (`.2`) |
| VRRP peer 2 | Third host (`.3`) |
| DHCP range start | Fourth host (`.4`) |
| DHCP range end | Last host |

## Requirements

```bash
pip install -r requirements.txt
```

## Usage

```bash
python render.py [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `-t`, `--template` | `dhcp.j2` | Jinja2 template file |
| `-i`, `--input` | `input.yaml` | YAML input file |
| `-o`, `--output` | stdout | Output file path |

### Examples

```bash
# Render to stdout
python render.py

# Custom input/template
python render.py -i my_vlans.yaml -t my_template.j2

# Write to file
python render.py -o dhcpd.conf
```

## Input format

```yaml
vlans:
  - id: 10
    name: servers
    subnets:
      - 192.168.10.0/24
  - id: 20
    name: workstations
    subnets:
      - 10.20.0.0/23
```

> **Note:** Copy `vars.yaml.example` as a starting point. `cp vars.yaml.example vars.yaml`

## Files

| File | Description |
|---|---|
| `render.py` | Main script |
| `dhcp.j2` | Jinja2 template for ISC DHCP config |
| `vars.yaml.example` | Example input structure |
| `requirements.txt` | Python dependencies |
