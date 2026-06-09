#!/usr/bin/env python3

import argparse
import ipaddress
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def enrich_subnet(cidr: str) -> dict:
    """Derive all DHCP fields from a CIDR string.

    Layout:
        host[0]  (.1)  — gateway
        host[1]  (.2)  — VRRP peer 1   } reserved
        host[2]  (.3)  — VRRP peer 2   }
        host[3]  (.4)  — first DHCP lease
        host[-1]       — last DHCP lease
    """
    net = ipaddress.IPv4Network(cidr, strict=False)
    hosts = list(net.hosts())

    if len(hosts) < 4:
        raise ValueError(
            f"Subnet {cidr} is too small — needs at least 4 usable hosts "
            f"(gateway + 2 VRRP + 1 DHCP lease)."
        )

    return {
        "cidr":            cidr,
        "network_address": str(net.network_address),
        "subnetmask":      str(net.netmask),
        "gateway":         str(hosts[0]),
        "range_start":     str(hosts[4]),
        "range_end":       str(hosts[-1]),
    }


def load_yaml(path: str) -> dict:
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "vlans" not in data:
        raise ValueError("YAML must contain a top-level 'vlans' key.")

    for vlan in data["vlans"]:
        vlan["subnets"] = [enrich_subnet(c) for c in vlan.get("subnets", [])]

    return data


def render_template(template_path: str, data: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(Path(template_path).parent)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template(Path(template_path).name).render(**data)


def main():
    parser = argparse.ArgumentParser(
        description="Render ISC DHCP config from VLAN ID + subnet CIDRs."
    )
    parser.add_argument("-t", "--template", default="dhcp.j2",
                        help="Jinja2 template file (default: dhcp.j2)")
    parser.add_argument("-i", "--input",    default="input.yaml",
                        help="YAML input file (default: input.yaml)")
    parser.add_argument("-o", "--output",   default=None,
                        help="Output file (default: stdout)")
    args = parser.parse_args()

    try:
        data = load_yaml(args.input)
    except FileNotFoundError:
        print(f"Error: '{args.input}' not found.", file=sys.stderr); sys.exit(1)
    except (ValueError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(1)

    try:
        rendered = render_template(args.template, data)
    except FileNotFoundError:
        print(f"Error: template '{args.template}' not found.", file=sys.stderr); sys.exit(1)
    except Exception as e:
        print(f"Template error: {e}", file=sys.stderr); sys.exit(1)

    if args.output:
        Path(args.output).write_text(rendered)
        print(f"Config written to: {args.output}")
    else:
    with open("output.txt", "w") as f:
        f.write(rendered)
    print(rendered)


if __name__ == "__main__":
    main()
