"""URL syntax and company identity; DNS enforcement is in the fetcher."""
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

PROFILE_HOSTS = {"crunchbase.com": "/organization/", "linkedin.com": "/company/"}


def public_ip(value):
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_reserved or address.is_multicast:
        return False
    if address.version == 6:
        # Reject legacy site-local and translation/tunnel routes that may embed private IPv4.
        return (address in ipaddress.IPv6Network("2000::/3")
                and not address.sixtofour and not address.teredo
                and not address.ipv4_mapped and not address.is_site_local)
    return True


def clean_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\s\\<>"\x00-\x1f\x7f]', value):
        raise ValueError("Invalid URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only HTTP(S) URLs without credentials are allowed")
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    if parsed.port not in {None, 80 if parsed.scheme == "http" else 443}:
        raise ValueError("Nonstandard ports are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host:
            raise ValueError("Invalid public hostname") from None
    else:
        if not public_ip(address):
            raise ValueError("Non-public address")
    authority = f"[{host}]" if ":" in host else host
    return urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))

