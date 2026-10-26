"""Fingerprint-based location matching"""


def signal_weight(rssi):
    """Importance weight of a fingerprint AP by its signal strength.

    -45 dBm and stronger => 1.0; -95 dBm and weaker => 0.1; linear between.
    Weak APs barely affect the score when they go missing, strong APs do.
    """
    return max(0.1, min(1.0, (rssi + 95.0) / 50.0))


def similarity(fp, scan):
    """Signal-weighted coverage score between a fingerprint and a scan (0-100).

    - Only fingerprint APs count: unrelated surrounding APs add no noise.
    - A missing AP costs its weight, so weak APs may drop out freely while
      a strong AP going missing drags the score down hard.
    - Present APs additionally lose points by signal drift (50 dBm full loss).
    """
    if not fp:
        return 0.0
    total = 0.0
    got = 0.0
    for bssid, rssi in fp.items():
        w = signal_weight(rssi)
        total += w
        cur = scan.get(bssid)
        if cur is not None:
            got += w * (1.0 - min(abs(rssi - cur) / 50.0, 1.0))
    if total <= 0:
        return 0.0
    return round(got / total * 100.0, 1)


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
