"""Pure comparison logic for realtor.ca price checks.

Kept free of Playwright/network imports so it can be unit-tested in isolation.
Takes the stored asking price plus a FetchResult and decides whether the live
listing price stayed the same, dropped, rose, is no longer listed, or could not
be checked.
"""

# Prices on realtor.ca are whole dollars; treat anything within $1 as "same" so
# rounding/formatting noise never reads as a change.
SAME_TOLERANCE = 1.0

# Status values produced by compare().
STATUS_SAME      = "same"
STATUS_DROPPED   = "dropped"
STATUS_RISEN     = "risen"
STATUS_NOT_FOUND = "not_found"   # listing genuinely gone (delisted / sold / 404)
STATUS_ERROR     = "error"       # could not check (blocked / timeout / parse fail)


def compare(stored_price, result) -> dict:
    """Compare a stored asking price against a fetched FetchResult.

    Returns a row dict: {status, stored, fetched, delta, delta_pct, listing_url}.
    ``delta`` and ``delta_pct`` are None unless both prices are known.
    """
    stored      = float(stored_price) if stored_price is not None else None
    listing_url = getattr(result, "listing_url", "") or ""
    outcome     = getattr(result, "outcome", "blocked")
    fetched     = getattr(result, "price", None)

    base = {
        "stored":      stored,
        "fetched":     None,
        "delta":       None,
        "delta_pct":   None,
        "listing_url": listing_url,
    }

    if outcome == "not_found":
        return {**base, "status": STATUS_NOT_FOUND}

    # Anything that isn't a clean "found" with a usable price can't be compared.
    if outcome != "found" or fetched is None:
        return {**base, "status": STATUS_ERROR}

    fetched = float(fetched)
    base["fetched"] = fetched

    # Without a stored price to compare against we can report the found price but
    # not a direction of change.
    if stored is None:
        return {**base, "status": STATUS_ERROR}

    delta = fetched - stored
    base["delta"]     = delta
    base["delta_pct"] = (delta / stored * 100.0) if stored else None

    if abs(delta) <= SAME_TOLERANCE:
        status = STATUS_SAME
    elif delta < 0:
        status = STATUS_DROPPED
    else:
        status = STATUS_RISEN

    return {**base, "status": status}
