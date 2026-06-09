import shutil
import subprocess
from pathlib import Path

import pytest

from render import enrich_subnet, format_option_value, load_yaml, render_template

REPO = Path(__file__).resolve().parent.parent


# --- enrich_subnet -----------------------------------------------------------

def test_enrich_subnet_defaults():
    result = enrich_subnet("192.168.1.0/24")

    assert result["cidr"] == "192.168.1.0/24"
    assert result["network_address"] == "192.168.1.0"
    assert result["subnetmask"] == "255.255.255.0"
    assert result["gateway"] == "192.168.1.1"
    assert result["range_start"] == "192.168.1.4"
    assert result["range_end"] == "192.168.1.254"
    assert result["log_requests"] is False


def test_enrich_subnet_custom_reservations():
    result = enrich_subnet("192.168.1.0/24", reserved_at_start=10, reserved_at_end=5)

    assert result["range_start"] == "192.168.1.11"
    assert result["range_end"] == "192.168.1.249"


def test_enrich_subnet_gateway_override():
    result = enrich_subnet("10.0.0.0/24", reserved_at_start=0, reserved_at_end=1,
                           gateway="10.0.0.254")

    assert result["gateway"] == "10.0.0.254"
    assert result["range_start"] == "10.0.0.1"
    assert result["range_end"] == "10.0.0.253"


def test_enrich_subnet_gateway_outside_subnet():
    with pytest.raises(ValueError, match="not inside the subnet"):
        enrich_subnet("10.0.0.0/24", gateway="192.168.1.1")


def test_enrich_subnet_gateway_inside_range():
    with pytest.raises(ValueError, match="falls inside the DHCP range"):
        enrich_subnet("10.0.0.0/24", reserved_at_start=0)


def test_enrich_subnet_too_small():
    with pytest.raises(ValueError, match="is too small"):
        enrich_subnet("192.168.1.0/30")


def test_enrich_subnet_reservations_exceed_subnet():
    with pytest.raises(ValueError, match="is too small"):
        enrich_subnet("192.168.1.0/28", reserved_at_start=10, reserved_at_end=10)


def test_enrich_subnet_negative_reservation():
    with pytest.raises(ValueError, match="must be >= 0"):
        enrich_subnet("192.168.1.0/24", reserved_at_start=-1)


# --- format_option_value -----------------------------------------------------

def test_format_option_value():
    assert format_option_value(["8.8.8.8", "1.1.1.1"]) == "8.8.8.8, 1.1.1.1"
    assert format_option_value("8.8.8.8") == "8.8.8.8"
    assert format_option_value("example.local") == '"example.local"'
    assert format_option_value('"already quoted"') == '"already quoted"'
    assert format_option_value(86400) == "86400"
    assert format_option_value(True) == "on"
    assert format_option_value(False) == "off"


# --- load_yaml ---------------------------------------------------------------

def write_yaml(tmp_path, content):
    f = tmp_path / "test.yaml"
    f.write_text(content)
    return str(f)


def test_load_yaml_full_schema(tmp_path):
    path = write_yaml(tmp_path, '''
global:
  parameters:
    authoritative: true
    default-lease-time: 86400
  options:
    domain-name-servers: [8.8.8.8, 1.1.1.1]
    domain-name: example.local
  raw: |
    option space acs;

defaults:
  reserved_at_start: 5

vlans:
  - id: 10
    description: test_vlan
    subnets:
      - 10.0.0.0/24
  - id: 20
    reserved_at_start: 1
    subnets:
      - cidr: 10.1.0.0/24
        reserved_at_start: 2
        log_requests: true
''')
    data = load_yaml(path)

    assert data["global_parameters"]["authoritative"] is True
    assert data["global_parameters"]["default-lease-time"] == 86400
    assert data["global_options"]["domain-name-servers"] == "8.8.8.8, 1.1.1.1"
    assert data["global_options"]["domain-name"] == '"example.local"'
    assert data["global_raw"] == "option space acs;"

    # defaults cascade: defaults -> vlan -> subnet
    assert data["vlans"][0]["subnets"][0]["range_start"] == "10.0.0.6"
    assert data["vlans"][1]["subnets"][0]["range_start"] == "10.1.0.3"
    assert data["vlans"][1]["subnets"][0]["log_requests"] is True
    assert data["vlans"][1]["description"] == ""


def test_load_yaml_no_global_section(tmp_path):
    path = write_yaml(tmp_path, '''
vlans:
  - id: 10
    subnets:
      - 10.0.0.0/24
''')
    data = load_yaml(path)

    assert data["global_parameters"] == {}
    assert data["global_options"] == {}
    assert data["global_raw"] == ""
    assert data["vlans"][0]["subnets"][0]["gateway"] == "10.0.0.1"


def test_load_yaml_missing_vlans(tmp_path):
    path = write_yaml(tmp_path, '''
global:
  options:
    domain-name-servers: [8.8.8.8]
''')
    with pytest.raises(ValueError, match="top-level 'vlans' key"):
        load_yaml(path)


def test_load_yaml_vlan_missing_id(tmp_path):
    path = write_yaml(tmp_path, '''
vlans:
  - description: no_id
    subnets:
      - 10.0.0.0/24
''')
    with pytest.raises(ValueError, match="needs an 'id'"):
        load_yaml(path)


def test_load_yaml_overlapping_subnets(tmp_path):
    path = write_yaml(tmp_path, '''
vlans:
  - id: 10
    subnets:
      - 10.0.0.0/23
  - id: 20
    subnets:
      - 10.0.1.0/24
''')
    with pytest.raises(ValueError, match="overlaps"):
        load_yaml(path)


# --- rendering ---------------------------------------------------------------

def render_example():
    data = load_yaml(str(REPO / "vars.yaml.example"))
    return render_template(str(REPO / "dhcp.j2"), data)


def test_render_example_contents():
    out = render_example()

    assert "authoritative;" in out
    assert "ddns-update-style none;" in out
    assert "default-lease-time 86400;" in out
    assert 'option domain-name "example.local";' in out
    assert "option domain-name-servers 8.8.8.8, 1.1.1.1;" in out
    assert 'option acs.url "https://acs.example.local:7547/";' in out
    assert "shared-network VLAN-403 {" in out
    assert "range 109.73.231.4 109.73.231.254;" in out
    assert "option routers 109.73.231.1;" in out
    assert "log(info" not in out  # logging is opt-in


def test_render_no_trailing_whitespace():
    for line in render_example().splitlines():
        assert line == line.rstrip(), f"trailing whitespace in: {line!r}"


@pytest.mark.skipif(shutil.which("dhcpd") is None, reason="dhcpd not installed")
def test_rendered_config_passes_dhcpd_syntax_check(tmp_path):
    conf = tmp_path / "dhcpd.conf"
    conf.write_text(render_example())

    proc = subprocess.run(["dhcpd", "-t", "-cf", str(conf)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
