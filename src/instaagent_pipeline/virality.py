"""Virality scoring for organic items.

The Apify scrapers provide engagement + creator metadata only; virality is recomputed
from reach + engagement since these providers do not supply a virality score.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

# Values at which each raw ratio reaches the top of its 0-1 log curve. REACH_CAP=100
# means "seen by 100x your followers" is maximally viral; ENGAGEMENT_CAP=0.30 means a
# 30% interaction rate is the engagement ceiling; VELOCITY_CAP=30 means reaching 30x
# your followers *per day* tops out the speed signal. All heavy-tailed, hence log.
# VELOCITY_CAP=30 is anchored to the p95 of observed (reach / age_days) so only the
# fastest ~5% saturate and there's ranking spread across the rest; revisit if the data
# mix shifts.
REACH_CAP = 100.0
ENGAGEMENT_CAP = 0.30
VELOCITY_CAP = 30.0

# Posts younger than this are treated as this old, so a few-hour-old rocket doesn't
# extrapolate to an absurd per-day velocity.
MIN_AGE_DAYS = 1.0

# How the 0.6 "reach budget" splits between all-time amplification and per-day velocity.
# 0.5 = balanced: fast risers get lifted, but proven all-time hits keep real credit.
# Raise toward 1.0 to make speed dominate (recency-heavy); drop toward 0.0 for the
# original age-unadjusted behavior.
RECENCY_STRENGTH = 0.5
_REACH_BUDGET = 0.6
ENGAGEMENT_WEIGHT = 0.4
AMPLIFICATION_WEIGHT = _REACH_BUDGET * (1 - RECENCY_STRENGTH)  # all-time reach
VELOCITY_WEIGHT = _REACH_BUDGET * RECENCY_STRENGTH  # reach per day


def _log_norm(ratio: float, cap: float) -> float:
    """Map a non-negative ratio onto [0, 1] via a log curve where `cap` -> 1.0.

    log spreads heavy tails so e.g. reach 10x vs 500x don't both flatten near 1 the
    way a plain ratio/(ratio+1) squash would.
    """
    if ratio <= 0:
        return 0.0
    return min(math.log1p(ratio) / math.log1p(cap), 1.0)


def _age_days(date_created: str | datetime | None, now: datetime) -> float | None:
    """Days since a post was created, floored at MIN_AGE_DAYS. None if the date is
    missing/unparseable (caller then degrades to the age-unadjusted blend). Future
    dates (clock skew) collapse to the floor rather than going negative."""
    if date_created is None:
        return None
    if isinstance(date_created, datetime):
        dt = date_created
    else:
        try:
            dt = datetime.fromisoformat(str(date_created).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return max((now - dt).total_seconds() / 86400.0, MIN_AGE_DAYS)


def recompute_virality(
    *,
    views: int | None,
    likes: int | None,
    comments: int | None,
    shares: int | None,
    followers: int | None = None,
    date_created: str | datetime | None = None,
    now: datetime | None = None,
) -> tuple[float | None, str | None]:
    """Normalized 0-1 virality blending reach amplification, reach *velocity*, and
    engagement rate. Each signal passes through the SAME log normalizer (`_log_norm`)
    so none is scaled while the others are clamped:
      amplification = views / followers            (cap REACH_CAP)     — all-time reach
      velocity      = amplification / age_days      (cap VELOCITY_CAP)  — reach per day
      engagement    = interactions / views          (cap ENGAGEMENT_CAP)

    Final score = AMPLIFICATION_WEIGHT*amp + VELOCITY_WEIGHT*velocity
                + ENGAGEMENT_WEIGHT*engagement, in [0, 1].

    Velocity is the age correction: raw cumulative views climb with a post's age, so an
    old slow-burn and a 2-day rocket that both reached 100x their audience look identical
    without it. When follower count is unknown the score degrades to engagement-only;
    when the posted date is unknown it degrades to the age-unadjusted reach blend (the
    original 0.6*reach + 0.4*engagement). Stands in for TopYappers' virality_score
    (TikTok/IG don't supply one).
    """
    if not views or views <= 0:
        return None, None
    engagement_rate = ((likes or 0) + (comments or 0) + (shares or 0)) / views
    engagement_norm = _log_norm(engagement_rate, ENGAGEMENT_CAP)
    if followers and followers > 0:
        reach = views / followers
        reach_norm = _log_norm(reach, REACH_CAP)
        age_days = _age_days(date_created, now or datetime.now(UTC))
        if age_days is not None:
            velocity_norm = _log_norm(reach / age_days, VELOCITY_CAP)
            score = round(
                AMPLIFICATION_WEIGHT * reach_norm
                + VELOCITY_WEIGHT * velocity_norm
                + ENGAGEMENT_WEIGHT * engagement_norm,
                3,
            )
        else:
            # No posted date → age-unadjusted blend (original behavior).
            score = round(_REACH_BUDGET * reach_norm + ENGAGEMENT_WEIGHT * engagement_norm, 3)
    else:
        score = round(engagement_norm, 3)
    if score >= 0.6:
        tier = "high"
    elif score >= 0.35:
        tier = "medium"
    elif score > 0:
        tier = "low"
    else:
        tier = None
    return score, tier
