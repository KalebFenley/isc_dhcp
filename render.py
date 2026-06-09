#!/usr/bin/env python3

import argparse
import ipaddress
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Per-subnet settings, overridable at the defaults, VLAN, or subnet level.
DEFAULTS = {
    "reserved_at_start": 3,   # gateway + 2 VRRP peers
    "reserved_at_end": 0,
    "log_requests": False,
}


def format_option_value(value) -> str:
    """Format a YAML value as an ISC dhcpd option value.

    Lists are joined with commas. Strings are quoted unless they parse as
    an IP address or are already quoted. Values this heuristic can't
    express (hex data, expressions, custom option spaces) belong in the
    global ``raw`` block instead.
    """
    if isinstance(value, list):
        return ", ".join(format_option_value(v) for v in value)
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if s.startswith('"') and s.endswith('"'):
        return s
    try:
        ipaddress.ip_address(s)
        return s
    except ValueError:
        return f'"{s}"'


def enrich_subnet(cidr: str, reserved_at_start: int = 3, reserved_at_end: int = 0,
                  gateway: str | None = None, log_requests: bool = False) -> dict:
    """Derive all DHCP fields from a CIDR string.

    Default layout (reserved_at_start=3):
        host[0]  (.1)  — gateway
        host[1]  (.2)  — VRRP peer 1   } reserved
        host[2]  (.3)  — VRRP peer 2   }
        host[3]  (.4)  — first DHCP lease
        host[-1]       — last DHCP lease
    """
    net = ipaddress.IPv4Network(cidr, strict=False)
    hosts = list(net.hosts())

    if reserved_at_start < 0 or reserved_at_end < 0:
        raise ValueError(f"Subnet {cidr}: reserved counts must be >= 0.")

    needed = reserved_at_start + reserved_at_end + 1
    if len(hosts) < needed:
        raise ValueError(
            f"Subnet {cidr} is too small — has {len(hosts)} usable hosts, "
            f"needs {needed} ({reserved_at_start} reserved at start + "
            f"{reserved_at_end} reserved at end + 1 DHCP lease)."
        )

    range_start = hosts[reserved_at_start]
    range_end = hosts[len(hosts) - 1 - reserved_at_end]

    if gateway is not None:
        gw = ipaddress.IPv4Address(str(gateway))
        if gw not in net:
            raise ValueError(f"Subnet {cidr}: gateway {gw} is not inside the subnet.")
    else:
        gw = hosts[0]

    if range_start <= gw <= range_end:
        raise ValueError(
            f"Subnet {cidr}: gateway {gw} falls inside the DHCP range "
            f"{range_start} - {range_end}; increase the reserved counts "
            f"or move the gateway."
        )

    return {
        "cidr":            cidr,
        "network_address": str(net.network_address),
        "subnetmask":      str(net.netmask),
        "gateway":         str(gw),
        "range_start":     str(range_start),
        "range_end":       str(range_end),
        "log_requests":    bool(log_requests),
    }


def load_yaml(path: str) -> dict:
    """Load the YAML configuration file, normalize it, and enrich subnets.

    Returns a dict ready to render, with these keys:
        global_parameters — dict of bare statements (values verbatim)
        global_options    — dict of option statements (values formatted)
        global_raw        — literal config passed through verbatim
        vlans             — list of VLANs with enriched subnet dicts
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "vlans" not in data:
        raise ValueError("YAML must contain a top-level 'vlans' key.")

    defaults = {**DEFAULTS, **(data.get("defaults") or {})}

    g = data.get("global") or {}
    data["global_parameters"] = g.get("parameters") or {}
    data["global_options"] = {
        name: format_option_value(value)
        for name, value in (g.get("options") or {}).items()
    }
    data["global_raw"] = (g.get("raw") or "").rstrip()

    seen = []  # (network, vlan_id, cidr) — for overlap detection
    for vlan in data["vlans"]:
        if "id" not in vlan:
            raise ValueError("Every VLAN needs an 'id'.")
        vlan.setdefault("description", "")

        subnets = []
        for entry in vlan.get("subnets") or []:
            if isinstance(entry, str):
                entry = {"cidr": entry}
            if "cidr" not in entry:
                raise ValueError(f"VLAN {vlan['id']}: subnet entries need a 'cidr'.")

            def pick(key):
                return entry.get(key, vlan.get(key, defaults[key]))

            subnets.append(enrich_subnet(
                entry["cidr"],
                reserved_at_start=pick("reserved_at_start"),
                reserved_at_end=pick("reserved_at_end"),
                gateway=entry.get("gateway"),
                log_requests=pick("log_requests"),
            ))

            net = ipaddress.IPv4Network(entry["cidr"], strict=False)
            for other_net, other_vid, other_cidr in seen:
                if net.overlaps(other_net):
                    raise ValueError(
                        f"Subnet {entry['cidr']} (VLAN {vlan['id']}) overlaps "
                        f"{other_cidr} (VLAN {other_vid})."
                    )
            seen.append((net, vlan["id"], entry["cidr"]))

        vlan["subnets"] = subnets

    return data


def render_template(template_path: str, data: dict) -> str:
    """Render the Jinja2 template with the provided data.

    Args:
        template_path: Path to the Jinja2 template file.
        data: Dictionary of data to pass into the template.

    Returns:
        The rendered template string.
    """
    env = Environment(
        loader=FileSystemLoader(str(Path(template_path).parent)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template(Path(template_path).name).render(**data)


def main():
    parser = argparse.ArgumentParser(
        description="Render a complete ISC DHCP config from VLAN IDs + subnet CIDRs."
    )
    parser.add_argument("-t", "--template", default="dhcp.j2",
                        help="Jinja2 template file (default: dhcp.j2)")
    parser.add_argument("-i", "--input",    default="vars.yaml",
                        help="YAML input file (default: vars.yaml)")
    parser.add_argument("-o", "--output",   default=None,
                        help="Output file (default: stdout)")
    args = parser.parse_args()

    try:
        data = load_yaml(args.input)
    except FileNotFoundError:
        print(f"Error: '{args.input}' not found.", file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        rendered = render_template(args.template, data)
    except FileNotFoundError:
        print(f"Error: template '{args.template}' not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Template error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        Path(args.output).write_text(rendered)
        print(f"Config written to: {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
