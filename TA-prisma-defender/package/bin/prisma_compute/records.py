"""Turn Console API responses into Splunk events.

Field names match the 1.0.0 add-on so existing searches keep working. Every
event gets ``record_type``:

* ``defender``                 one per Defender (connected and disconnected)
* ``defenders_summary``        Defender counts per category (connected/deployed/licensed)
* ``registry_scan_progress``   one per registry scan (discovery + image scan progress)
* ``registry_scan_statistics`` totals across all registry scans
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

_FEATURES = (
    ("runtime", "Runtime"),
    ("filesystem", "Filesystem"),
    ("network", "Network"),
    ("process", "Process"),
    ("appFirewall", "AppFirewall"),
    ("containerNetworkFirewall", "ContainerNetworkFirewall"),
    ("hostNetworkFirewall", "HostNetworkFirewall"),
)


def format_datetime(value: Optional[str]) -> str:
    if not value:
        return "N/A"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        # Python 3.9's fromisoformat rejects >6 fractional digits; keep the raw value.
        return str(value)


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def defender_record(defender: Dict[str, Any]) -> Dict[str, Any]:
    cloud = _dict(defender.get("cloudMetadata"))
    system_info = _dict(defender.get("systemInfo"))
    status = _dict(defender.get("status"))

    features = [label for key, label in _FEATURES if _dict(status.get(key)).get("enabled")]
    errors = [
        "{}: {}".format(feature, data["err"])
        for feature, data in status.items()
        if isinstance(data, dict) and data.get("err")
    ]
    return {
        "record_type": "defender",
        "hostname": defender.get("hostname", "N/A"),
        "fqdn": defender.get("fqdn", "N/A"),
        "cluster": defender.get("cluster", "N/A"),
        "cluster_type": defender.get("clusterType", "N/A"),
        "cluster_id": defender.get("clusterID", "N/A"),
        "type": defender.get("type", "N/A"),
        "category": defender.get("category", "N/A"),
        "version": defender.get("version", "N/A"),
        "connected": defender.get("connected", False),
        "last_modified": format_datetime(defender.get("lastModified")),
        "certificate_expiration": format_datetime(defender.get("certificateExpiration")),
        "cloud_provider": cloud.get("provider", "N/A"),
        "cloud_account": cloud.get("accountID", "N/A"),
        "cloud_region": cloud.get("region", "N/A"),
        "cpu_count": system_info.get("cpuCount", "N/A"),
        "memory_gb": system_info.get("memoryGB", "N/A"),
        "kernel_version": system_info.get("kernelVersion", "N/A"),
        "free_disk_gb": system_info.get("freeDiskSpaceGB", "N/A"),
        "total_disk_gb": system_info.get("totalDiskSpaceGB", "N/A"),
        "collections": ", ".join(str(c) for c in (defender.get("collections") or [])) or "None",
        "features_enabled": ", ".join(features) or "None",
        "is_arm64": defender.get("isARM64", False),
        "vpc_observer": defender.get("vpcObserver", False),
        "remote_mgmt_supported": defender.get("remoteMgmtSupported", False),
        "remote_logging_supported": defender.get("remoteLoggingSupported", False),
        "using_old_ca": defender.get("usingOldCA", False),
        "compatible_version": defender.get("compatibleVersion", False),
        "errors": "; ".join(errors) if errors else "None",
    }


def defenders_summary_record(data: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """``[{category, connected, deployed, licensed}, ...]`` -> ``{col: {category: n}}``."""
    rows = [r for r in data if isinstance(r, dict) and "category" in r]
    if not rows:
        return None
    columns: List[str] = []
    for row in rows:
        for key in row:
            if key != "category" and key not in columns:
                columns.append(key)
    summary = {col: {str(row["category"]): row.get(col) for row in rows} for col in columns}
    return {"record_type": "defenders_summary", "defenders_summary": summary}


def registry_records(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One event per registry scan, plus a statistics event (if there are scans)."""
    out: List[Dict[str, Any]] = []
    for record in data:
        if not isinstance(record, dict):
            continue
        discovery = _dict(record.get("discovery"))
        image_scan = _dict(record.get("imageScan"))
        error = discovery.get("error")
        error_message, scanned_by = None, None
        if error:
            parts = str(error).split(", scanned by defender: ")
            error_message = parts[0]
            scanned_by = parts[1] if len(parts) == 2 else None
        out.append({
            "record_type": "registry_scan_progress",
            "discovery_id": discovery.get("id"),
            "discovery_type": discovery.get("type"),
            "discovery_discovery": discovery.get("discovery"),
            "discovery_total": discovery.get("total"),
            "discovery_scanned": discovery.get("scanned"),
            "discovery_title": discovery.get("title"),
            "discovery_error": error,
            "imageScan_id": image_scan.get("id"),
            "imageScan_type": image_scan.get("type"),
            "imageScan_discovery": image_scan.get("discovery"),
            "imageScan_total": image_scan.get("total"),
            "imageScan_scanned": image_scan.get("scanned"),
            "imageScan_title": image_scan.get("title"),
            "isScanOngoing": record.get("isScanOngoing"),
            "specScanStartTime": record.get("specScanStartTime"),
            "error_message": error_message,
            "defender": scanned_by,
        })
    if out:
        def total(key: str) -> int:
            return sum(int(r.get(key) or 0) for r in out)

        with_errors = sum(1 for r in out if r["error_message"])
        out.append({
            "record_type": "registry_scan_statistics",
            "total_records_processed": len(out),
            "statistics": {
                "total_records": len(out),
                "total_discovery_repositories": total("discovery_total"),
                "total_discovery_scanned": total("discovery_scanned"),
                "total_images": total("imageScan_total"),
                "total_images_scanned": total("imageScan_scanned"),
                "records_with_errors": with_errors,
                "records_without_errors": len(out) - with_errors,
            },
        })
    return out
