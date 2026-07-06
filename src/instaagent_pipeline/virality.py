"""Virality scoring for organic items.

The Apify scrapers provide engagement + creator metadata only; virality is recomputed
from reach + engagement since these providers do not supply a virality score.
"""

from __future__ import annotations

import math

# Values at which each raw ratio reaches the top of its 0-1 log curve. REACH_CAP=100
# means "seen by 100x your followers" is maximally viral; ENGAGEMENT_CAP=0.30 means a
# 30% interaction rate is the engagement ceiling. Both are heavy-tailed, hence log.
REACH_CAP = 100.0
ENGAGEMENT_CAP = 0.30


def _log_norm(ratio: float, cap: float) -> float:
    """Map a non-negative ratio onto [0, 1] via a log curve where `cap` -> 1.0.

    log spreads heavy tails so e.g. reach 10x vs 500x don't both flatten near 1 the
    way a plain ratio/(ratio+1) squash would.
    """
    if ratio <= 0:
        return 0.0
    return min(math.log1p(ratio) / math.log1p(cap), 1.0)


def recompute_virality(
    *,
    views: int | None,
    likes: int | None,
    comments: int | None,
    shares: int | None,
    followers: int | None = None,
) -> tuple[float | None, str | None]:
    """Normalized 0-1 virality blending reach amplification with engagement rate.

    Both signals pass through the SAME log normalizer (`_log_norm`) so neither is
    scaled while the other is clamped:
      reach      = views / followers          (cap REACH_CAP)
      engagement = interactions / views       (cap ENGAGEMENT_CAP)
    Final score = 0.6*reach + 0.4*engagement, in [0, 1]. When follower count is
    unknown the score degrades to engagement-only. Stands in for TopYappers'
    virality_score (TikTok/IG don't supply one).
    """
    if not views or views <= 0:
        return None, None
    engagement_rate = ((likes or 0) + (comments or 0) + (shares or 0)) / views
    engagement_norm = _log_norm(engagement_rate, ENGAGEMENT_CAP)
    if followers and followers > 0:
        reach_norm = _log_norm(views / followers, REACH_CAP)
        score = round(0.6 * reach_norm + 0.4 * engagement_norm, 3)
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
