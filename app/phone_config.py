from ipaddress import ip_address, ip_network

TAILSCALE_IPV4_RANGE = ip_network("100.64.0.0/10")


def normalize_tailscale_ipv4(value):
    if value is None:
        return ""

    text = str(value).strip()
    try:
        address = ip_address(text)
    except ValueError:
        return ""

    if address.version != 4 or address not in TAILSCALE_IPV4_RANGE:
        return ""

    return str(address)


def is_valid_tailscale_ipv4(value):
    return bool(normalize_tailscale_ipv4(value))
