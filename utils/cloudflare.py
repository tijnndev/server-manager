import requests
from typing import Optional

API_BASE = "https://api.cloudflare.com/client/v4"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


def extract_zone_name(domain: str) -> str:
    domain = (domain or "").lstrip("*.").strip().lower()
    parts = domain.split('.')
    if len(parts) >= 2:
        return '.'.join(parts[-2:])
    return domain


def _best_match_zone(domain: str, zones: list) -> Optional[str]:
    domain = (domain or "").lower()
    best = None
    for zone in zones:
        name = (zone.get("name") or "").lower()
        if domain == name or domain.endswith("." + name):
            # prefer longest match
            if not best or len(name) > len(best.get("name", "")):
                best = zone
    return best.get("id") if best else None


def get_zone_id(token: str, zone_name: str) -> Optional[str]:
    zone_name = (zone_name or "").strip().lower()
    if not zone_name:
        return None

    params = {"name": zone_name, "per_page": 50, "status": "active"}
    resp = requests.get(f"{API_BASE}/zones", headers=_headers(token), params=params, timeout=10)
    if resp.ok:
        data = resp.json()
        if data.get("success"):
            result = data.get("result") or []
            zone_id = _best_match_zone(zone_name, result)
            if zone_id:
                return zone_id

    # Fallback: list accessible zones and find best suffix match (supports zone-scoped tokens)
    fallback_resp = requests.get(f"{API_BASE}/zones", headers=_headers(token), params={"per_page": 50, "status": "active"}, timeout=10)
    if not fallback_resp.ok:
        return None
    fallback_data = fallback_resp.json()
    if not fallback_data.get("success"):
        return None
    zones = fallback_data.get("result") or []
    return _best_match_zone(zone_name, zones)


def create_dns_record(token: str, zone_id: str, record_type: str, name: str, content: str, proxied: bool = False, ttl: int = 120) -> dict:
    payload = {
        "type": record_type,
        "name": name,
        "content": content,
        "ttl": ttl,
        "proxied": proxied,
    }
    resp = requests.post(f"{API_BASE}/zones/{zone_id}/dns_records", headers=_headers(token), json=payload, timeout=10)
    return resp.json()


def find_dns_record(token: str, zone_id: str, name: str, record_type: str) -> Optional[str]:
    params = {"name": name, "type": record_type, "per_page": 1}
    resp = requests.get(f"{API_BASE}/zones/{zone_id}/dns_records", headers=_headers(token), params=params, timeout=10)
    if not resp.ok:
        return None
    data = resp.json()
    if not data.get("success"):
        return None
    results = data.get("result") or []
    if not results:
        return None
    return results[0].get("id")


def delete_dns_record(token: str, zone_id: str, record_id: str) -> dict:
    resp = requests.delete(f"{API_BASE}/zones/{zone_id}/dns_records/{record_id}", headers=_headers(token), timeout=10)
    return resp.json()
