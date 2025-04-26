import sqlite3
from datetime import datetime, date
from collections import defaultdict
from typing import List, Dict, Tuple, Optional

# Path to your SQLite database file
DBPATH = './data/speciesid.db'

def _connect():
    """Open a new database connection and set row factory."""
    conn = sqlite3.connect(DBPATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn


def get_common_name(scientific_name: str) -> str:
    """
    Look up the human‐friendly common name for a given scientific name.
    Returns the scientific name itself if no mapping is found.
    """
    conn = _connect()
    cur = conn.execute(
        "SELECT common_name FROM species_lookup WHERE scientific_name = ?",
        (scientific_name,)
    )
    row = cur.fetchone()
    conn.close()
    return row['common_name'] if row else scientific_name


def recent_detections(limit: int = 10) -> List[Dict]:
    """
    Fetch the most recent `limit` detections (best model guess),
    returning a list of dicts with all fields from `detections`.
    """
    conn = _connect()
    cur = conn.execute(
        """
        SELECT id, detection_time, detection_index, score,
               display_name, category_name, frigate_event,
               camera_name, reviewed
          FROM detections
         ORDER BY detection_time DESC
         LIMIT ?
        """,
        (limit,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_detection_choices(event_id: str) -> List[Tuple[str, float]]:
    """
    Return the list of (display_name, score) for the top-5
    model candidates for a given event_id, ordered by rank.
    """
    conn = _connect()
    cur = conn.execute(
        """
        SELECT display_name, score
          FROM detection_choices
         WHERE event_id = ?
         ORDER BY rank
        """,
        (event_id,)
    )
    choices = [(r['display_name'], r['score']) for r in cur.fetchall()]
    conn.close()
    return choices


def get_daily_summary(day: date) -> Dict[str, object]:
    """
    Build a summary mapping scientific_name → {
      'scientific_name', 'common_name', 'total_detections', 'hourly_detections': [counts…]
    } for the given date.
    """
    conn = _connect()
    # zero‐initialize a dict of hour bins 0–23
    summary = defaultdict(lambda: {'scientific_name': None,
                                   'common_name': None,
                                   'total_detections': 0,
                                   'hourly_detections': [0]*24})
    cur = conn.execute(
        """
        SELECT category_name AS scientific_name,
               COUNT(*) AS cnt,
               STRFTIME('%H', detection_time) AS hr
          FROM detections
         WHERE DATE(detection_time) = ?
           AND reviewed = 1           -- only include reviewed for the official summary
         GROUP BY scientific_name, hr
        """,
        (day.isoformat(),)
    )
    for row in cur:
        sci = row['scientific_name']
        hr = int(row['hr'])
        cnt = row['cnt']
        summary[sci]['scientific_name'] = sci
        summary[sci]['common_name'] = get_common_name(sci)
        summary[sci]['total_detections'] += cnt
        summary[sci]['hourly_detections'][hr] = cnt

    conn.close()
    return summary


def get_records_for_date_hour(day: date, hour: int) -> List[Dict]:
    """
    Return all detections for a given date and hour,
    ordered by detection_time ascending.
    """
    conn = _connect()
    cur = conn.execute(
        """
        SELECT *
          FROM detections
         WHERE DATE(detection_time) = ?
           AND STRFTIME('%H', detection_time) = ?
        ORDER BY detection_time ASC
        """,
        (day.isoformat(), f"{hour:02d}")
    )
    recs = [dict(r) for r in cur.fetchall()]
    conn.close()
    return recs


def get_records_for_scientific_name_and_date(scientific_name: str,
                                             day: date,
                                             end_date: Optional[date] = None
                                             ) -> List[Dict]:
    """
    Return all detections of a given species for a date or date range.
    """
    conn = _connect()
    if end_date:
        cur = conn.execute(
            """
            SELECT *
              FROM detections
             WHERE category_name = ?
               AND DATE(detection_time) BETWEEN ? AND ?
            ORDER BY detection_time ASC
            """,
            (scientific_name, day.isoformat(), end_date.isoformat())
        )
    else:
        cur = conn.execute(
            """
            SELECT *
              FROM detections
             WHERE category_name = ?
               AND DATE(detection_time) = ?
            ORDER BY detection_time ASC
            """,
            (scientific_name, day.isoformat())
        )
    recs = [dict(r) for r in cur.fetchall()]
    conn.close()
    return recs


def get_earliest_detection_date() -> date:
    """
    Return the date of the very first detection in the db.
    """
    conn = _connect()
    row = conn.execute(
        "SELECT MIN(DATE(detection_time)) AS d FROM detections"
    ).fetchone()
    conn.close()
    return datetime.fromisoformat(row['d']).date() if row and row['d'] else date.today()


# ——— New review-flag functions ——————————————————————————————————

def get_reviewed_detections(limit: int = 50) -> List[Dict]:
    """
    Fetch the most recent detections that have been marked reviewed.
    """
    conn = _connect()
    cur = conn.execute(
        """
        SELECT *
          FROM detections
         WHERE reviewed = 1
         ORDER BY detection_time DESC
         LIMIT ?
        """,
        (limit,)
    )
    recs = [dict(r) for r in cur.fetchall()]
    conn.close()
    return recs


def get_unreviewed_detections(limit: int = 50) -> List[Dict]:
    """
    Fetch the most recent detections that have NOT been reviewed.
    """
    conn = _connect()
    cur = conn.execute(
        """
        SELECT *
          FROM detections
         WHERE reviewed = 0
         ORDER BY detection_time DESC
         LIMIT ?
        """,
        (limit,)
    )
    recs = [dict(r) for r in cur.fetchall()]
    conn.close()
    return recs

