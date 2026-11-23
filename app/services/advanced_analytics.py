from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Float, Integer, and_, case, cast, extract, func, or_, select

from app.models import APIEndpoint, Incident, MonitoringHistory
from app.services.probe_history import AVAILABILITY_STATUSES
from app.services.scheduler import INTERVAL


RANGES = {"1h": (3600, 60), "6h": (21600, 300), "24h": (86400, 1200), "7d": (604800, 8400)}
GAP_SECONDS = int(INTERVAL.total_seconds() * 2.5)
HISTOGRAM_EDGES = (0, 50, 100, 250, 500, 1000, 2500, 5000)
COMPARISON_LIMIT = 15
CHECKS_LIMIT = 24
History = MonitoringHistory


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    bucket_seconds: int
    bucket_count: int

    @classmethod
    def from_range(cls, requested, end=None):
        seconds, bucket = RANGES[requested]
        # Use whole-second boundaries so visual buckets and exact check lookups share the same bounds.
        end = utc(end).replace(microsecond=0) if end else datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=1)
        return cls(end - timedelta(seconds=seconds), end, bucket, seconds // bucket)

    def bucket_bounds(self, index):
        start = self.start + timedelta(seconds=self.bucket_seconds * index)
        return start, start + timedelta(seconds=self.bucket_seconds)


def date_seconds(db, column):
    if db.get_bind().dialect.name == "sqlite":
        return cast(func.strftime("%s", func.substr(column, 1, 19)), Float) + cast(
            func.coalesce(func.nullif(func.substr(column, 20, 7), ""), "0"), Float,
        )
    return extract("epoch", column)


def valid_latency(column):
    return and_(column >= 0, column < float("inf"))


def availability_totals(status, latency):
    measured = status.in_(AVAILABILITY_STATUSES)
    eligible = and_(measured, valid_latency(latency))
    return (
        func.count().filter(status == "UP").label("successful"),
        func.count().filter(and_(measured, status != "UP")).label("unsuccessful"),
        func.count().filter(status == "ERROR").label("monitoring_errors"),
        func.count().filter(eligible).label("latency_samples"),
        func.avg(latency).filter(eligible).label("average"),
    )


def report_availability(row):
    return {name: row[name] for name in ("successful", "unsuccessful", "monitoring_errors")}


def sample_filter(endpoint_id, start, end):
    return and_(History.endpoint_id == endpoint_id, History.checked_at >= start, History.checked_at < end)


def samples_in_window(db, endpoint_id, window):
    epoch = date_seconds(db, History.checked_at)
    bucket = cast(func.floor((epoch - window.start.timestamp()) / window.bucket_seconds), Integer)
    return select(
        History.id, History.checked_at, History.status, History.status_code, History.reason,
        History.response_time, epoch.label("epoch"), bucket.label("bucket"),
    ).where(sample_filter(endpoint_id, window.start, window.end)).cte("window_samples")


def distribution(db, samples):
    eligible = select(samples.c.response_time.label("ms")).where(
        samples.c.status.in_(AVAILABILITY_STATUSES), valid_latency(samples.c.response_time),
    ).subquery()
    ms = eligible.c.ms
    levels = (("median", 0.5, 2), ("p95", 0.95, 20), ("p99", 0.99, 100))
    limits = (*HISTOGRAM_EDGES[1:], None)
    bins = [func.count().filter(and_(ms >= start, ms < end) if end is not None else ms >= start).label(f"bin_{i}")
            for i, (start, end) in enumerate(zip(HISTOGRAM_EDGES, limits))]

    if db.get_bind().dialect.name == "postgresql":
        percentiles = [func.percentile_cont(q).within_group(ms).label(key) for key, q, _ in levels]
        row = db.execute(select(func.count().label("samples"), func.avg(ms).label("average"),
                                func.max(ms).label("maximum"), *percentiles, *bins)).mappings().one()
        stats = dict(row)
    else:
        # SQLite doesn't provide ordered-set aggregates. Select only the six interpolation ranks.
        row = db.execute(select(func.count().label("samples"), func.avg(ms).label("average"),
                                func.max(ms).label("maximum"), *bins)).mappings().one()
        stats = dict(row)
        positions = {key: (row["samples"] - 1) * q for key, q, minimum in levels if row["samples"] >= minimum}
        if positions:
            ranked = select(ms, func.row_number().over(order_by=ms).label("rank")).subquery()
            ranks = {int(position) + offset for position in positions.values() for offset in (1, 2)
                     if int(position) + offset <= row["samples"]}
            values = dict(db.execute(select(ranked.c.rank, ranked.c.ms).where(ranked.c.rank.in_(ranks))).all())
            for key, position in positions.items():
                rank = int(position) + 1
                low = values[rank]
                stats[key] = low + (values.get(rank + 1, low) - low) * (position % 1)

    statistics = {name: stats[name] for name in ("samples", "average", "maximum")}
    statistics.update({key: stats[key] if stats["samples"] >= minimum else None for key, _, minimum in levels})
    histogram = [{"lower": start, "upper": end, "count": stats[f"bin_{i}"]}
                 for i, (start, end) in enumerate(zip(HISTOGRAM_EDGES, limits))]
    return statistics, histogram


def ordered_samples(samples):
    order = (samples.c.checked_at, samples.c.id)
    usable_success = and_(samples.c.status == "UP", valid_latency(samples.c.response_time))
    return select(
        samples,
        func.lag(samples.c.epoch).over(order_by=order).label("previous_epoch"),
        func.lag(case((usable_success, 1), else_=0), 1, 0).over(order_by=order).label("previous_success"),
    ).cte("ordered_samples")


def timeline_buckets(db, ordered, window):
    row = ordered.c
    gap = row.epoch - func.coalesce(row.previous_epoch, window.start.timestamp()) > GAP_SECONDS
    buckets = [dict(item) for item in db.execute(select(
        row.bucket.label("index"),
        func.count().filter(row.status == "UP").label("successful"),
        func.count().filter(row.status.in_(("DOWN", "REDIRECT"))).label("unsuccessful"),
        func.count().filter(row.status == "ERROR").label("monitoring_errors"),
        func.count().filter(gap).label("gaps"),
        func.max(row.epoch).label("latest_epoch"),
    ).group_by(row.bucket).order_by(row.bucket)).mappings()]
    if buckets and window.end.timestamp() - float(buckets[-1]["latest_epoch"]) > GAP_SECONDS:
        buckets[-1]["gaps"] += 1
    for bucket in buckets:
        del bucket["latest_epoch"]
    return buckets


def trend_points(db, ordered):
    row = ordered.c
    chronological = (row.checked_at, row.id)
    successful = and_(row.status == "UP", valid_latency(row.response_time))
    discontinuity = or_(row.previous_success == 0, row.epoch - row.previous_epoch > GAP_SECONDS)
    # Segment raw checks before choosing plotted points, so omitted checks cannot hide outages.
    segment = func.sum(case((and_(successful, discontinuity), 1), else_=0)).over(
        order_by=chronological, rows=(None, 0),
    )
    continuous = select(ordered, case((successful, segment)).label("segment")).subquery()
    sample = continuous.c
    partition = (sample.bucket, sample.status == "UP")
    orderings = (
        (sample.checked_at, sample.id), (sample.checked_at.desc(), sample.id.desc()),
        (sample.response_time, sample.id), (sample.response_time.desc(), sample.id),
    )
    representatives = select(continuous, *[
        func.row_number().over(partition_by=partition, order_by=order).label(f"rank_{i}")
        for i, order in enumerate(orderings)
    ]).where(sample.status.in_(AVAILABILITY_STATUSES), valid_latency(sample.response_time)).subquery()
    row = representatives.c
    rows = db.execute(select(row.id, row.checked_at, row.status, row.status_code, row.response_time, row.reason, row.segment)
                      .where(or_(*(row[f"rank_{i}"] == 1 for i in range(4))))
                      .order_by(row.checked_at, row.id)).mappings().all()
    return [{**item, "checked_at": utc(item["checked_at"])} for item in rows]


def endpoint_report(db, endpoint, window):
    samples = samples_in_window(db, endpoint.id, window)
    ordered = ordered_samples(samples)
    timeline = timeline_buckets(db, ordered, window)
    totals = {key: sum(row[key] for row in timeline)
              for key in ("successful", "unsuccessful", "monitoring_errors")}
    measured = totals["successful"] + totals["unsuccessful"]
    statistics, histogram = distribution(db, samples)
    return {
        "id": endpoint.id, "name": endpoint.name, "availability": totals,
        "uptime": 100 * totals["successful"] / measured if measured else None,
        "latency": statistics, "histogram": histogram, "timeline": timeline,
        "trend": trend_points(db, ordered), "gap_seconds": GAP_SECONDS,
    }


def comparison_report(db, owner, window, metric, offset, descending):
    owned = select(APIEndpoint.id, APIEndpoint.name).where(APIEndpoint.user_id == owner).cte("owned_endpoints")
    counts = select(History.endpoint_id, *availability_totals(History.status, History.response_time)).join(
        owned, owned.c.id == History.endpoint_id,
    ).where(History.checked_at >= window.start, History.checked_at < window.end).group_by(History.endpoint_id).subquery()
    measured = counts.c.successful + counts.c.unsuccessful
    values = {
        "uptime": 100.0 * counts.c.successful / func.nullif(measured, 0),
        "latency": counts.c.average, "successful": counts.c.successful,
        "unsuccessful": counts.c.unsuccessful, "measured": measured,
    }
    value = case((measured > 0, values[metric]))
    rows = db.execute(select(
        owned.c.id, owned.c.name, value.label("value"),
        func.coalesce(counts.c.latency_samples if metric == "latency" else measured, 0).label("samples"),
        func.max(value).over().label("maximum"), func.count().over().label("total"),
    ).outerjoin(counts, counts.c.endpoint_id == owned.c.id).order_by(
        (value.desc() if descending else value.asc()).nulls_last(), func.lower(owned.c.name), owned.c.id,
    ).offset(offset).limit(COMPARISON_LIMIT)).mappings().all()
    total = rows[0]["total"] if rows else db.scalar(select(func.count()).select_from(owned))
    return {"items": rows, "maximum": rows[0]["maximum"] if rows else None, "total": total,
            "offset": offset, "limit": COMPARISON_LIMIT}


def incident_report(db, owner, window, endpoint_id):
    owned = [Incident.owner_id == owner]
    if endpoint_id is not None:
        owned.append(Incident.endpoint_id == endpoint_id)
    overlapping = and_(Incident.started_at < window.end,
                       or_(Incident.resolved_at.is_(None), Incident.resolved_at > window.start))
    opened = and_(Incident.detected_at >= window.start, Incident.detected_at < window.end)
    resolved = and_(Incident.resolved_at >= window.start, Incident.resolved_at < window.end)
    recovered = and_(resolved, Incident.resolution == "recovered")
    stats = db.execute(select(
        func.count().filter(overlapping).label("overlapping"),
        func.count().filter(opened).label("opened"),
        func.count().filter(recovered).label("recovered"),
        func.count().filter(and_(resolved, Incident.resolution == "manual")).label("manually_resolved"),
        func.avg(date_seconds(db, Incident.resolved_at) - date_seconds(db, Incident.started_at))
        .filter(and_(recovered, Incident.resolved_at >= Incident.started_at)).label("average_recovery_seconds"),
    ).where(*owned, or_(overlapping, opened, resolved))).mappings().one()

    # Group by current endpoint identity; keep deleted endpoints' historical labels separate.
    current_name = func.coalesce(APIEndpoint.name, Incident.endpoint_name)
    affected = db.execute(select(
        Incident.endpoint_id.label("id"), current_name.label("name"), func.count().label("incidents"),
    ).outerjoin(APIEndpoint, and_(APIEndpoint.id == Incident.endpoint_id, APIEndpoint.user_id == owner))
        .where(*owned, overlapping).group_by(Incident.endpoint_id, current_name)
        .order_by(func.count().desc(), current_name, Incident.endpoint_id).limit(8)).mappings().all()
    return {**stats, "affected": affected}


def exact_bucket(db, endpoint_id, window, bucket, cursor_at, cursor_id):
    start, end = window.bucket_bounds(bucket)
    query = select(
        History.id, History.checked_at, History.status, History.status_code, History.reason,
        case((valid_latency(History.response_time), History.response_time)).label("response_time"),
    ).where(sample_filter(endpoint_id, start, end))
    if cursor_at is not None:
        query = query.where(or_(History.checked_at > cursor_at,
                                and_(History.checked_at == cursor_at, History.id > cursor_id)))
    rows = db.execute(query.order_by(History.checked_at, History.id).limit(CHECKS_LIMIT + 1)).mappings().all()
    items = [{**row, "checked_at": utc(row["checked_at"])} for row in rows[:CHECKS_LIMIT]]
    cursor = {"at": items[-1]["checked_at"], "id": items[-1]["id"]} if len(rows) > CHECKS_LIMIT else None
    return {"items": items, "next_cursor": cursor}
