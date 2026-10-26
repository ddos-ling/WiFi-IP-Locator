"""Fingerprint-based location matching"""


def similarity(fp, scan):
    """Score similarity between a fingerprint and the current scan.

    fp / scan: {bssid: rssi}
    Returns 0-100. Half weight on AP coverage, half on signal closeness
    (50 dBm difference treated as fully mismatched).
    """
    if not fp or not scan:
        return 0.0
    common = set(fp) & set(scan)
    if not common:
        return 0.0
    coverage = len(common) / max(len(fp), len(scan))
    signal = sum(1.0 - min(abs(fp[b] - scan[b]) / 50.0, 1.0) for b in common) / len(common)
    return round((0.5 * coverage + 0.5 * signal) * 100, 1)


def evaluate_points(points, scan):
    """Evaluate all points against the current scan.

    Returns a list of dicts sorted by score desc:
    {name, id, score, threshold, matched}
    """
    scan_map = {r["bssid"]: r["rssi"] for r in scan}
    results = []
    for pt in points:
        fp = {f["bssid"]: f["rssi"] for f in pt.get("fingerprint", [])}
        score = similarity(fp, scan_map)
        threshold = float(pt.get("threshold", 75))
        results.append({
            "id": pt["id"],
            "name": pt.get("name", "?"),
            "score": score,
            "threshold": threshold,
            "matched": score >= threshold,
        })
    results.sort(key=lambda x: -x["score"])
    return results


def best_match(points, scan):
    """Return the best matched point dict or None when off-tolerance.

    Returns (point, results)
    """
    results = evaluate_points(points, scan)
    by_id = {p["id"]: p for p in points}
    for r in results:
        if r["matched"]:
            return by_id.get(r["id"]), results
    return None, results
