"""Local PostgreSQL maintenance command. Defaults to a read-only eligibility report."""

import argparse
from contextlib import closing
from dataclasses import dataclass
from datetime import timedelta, timezone
import os
from time import sleep

import psycopg2


RETENTION_LOCK = 1414679401


class RetentionRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class RetentionPlan:
    database: str
    days: int = 90
    batch_size: int = 500
    max_batches: int = 100
    apply: bool = False
    confirmation: str | None = None

    def validate(self, enabled=False):
        if not (1 <= self.days <= 36500 and 1 <= self.batch_size <= 2000 and 1 <= self.max_batches <= 1000):
            raise RetentionRefused("Retention duration or batch bounds are invalid.")
        if self.apply and (not enabled or self.confirmation != self.database):
            raise RetentionRefused("Deletion requires MONITORING_RETENTION_ENABLED=true and an exact database confirmation.")


def run_retention(connection, plan, *, enabled=False, pause=sleep):
    plan.validate(enabled)
    acquired = False
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '30s'")
                if not plan.apply:
                    cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT current_database(), clock_timestamp()")
                name, now = cursor.fetchone()
                if name != plan.database:
                    raise RetentionRefused("Connected database does not match the requested target.")
                cutoff = now.astimezone(timezone.utc) - timedelta(days=plan.days)
                if not plan.apply:
                    cursor.execute("SELECT count(*) FROM public.monitoring_history WHERE checked_at < %s", (cutoff,))
                    return {"mode": "dry-run", "cutoff": cutoff.isoformat(), "eligible": cursor.fetchone()[0], "deleted": 0}

                cursor.execute("SELECT has_table_privilege(current_user, 'public.monitoring_history', 'DELETE')")
                if not cursor.fetchone()[0]:
                    raise RetentionRefused("The connected database role lacks monitoring-history DELETE permission.")
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (RETENTION_LOCK,))
                acquired = cursor.fetchone()[0]
                if not acquired:
                    raise RetentionRefused("Another retention run is active for this database.")

        deleted = batches = 0
        endpoint = 0
        while batches < plan.max_batches:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '5s'")
                    cursor.execute("SET LOCAL lock_timeout = '1s'")
                    cursor.execute("SELECT id FROM public.api_endpoints WHERE id > %s ORDER BY id LIMIT 1", (endpoint,))
                    found = cursor.fetchone()
                    if found is None:
                        break
                    next_endpoint = found[0]
                    cursor.execute("""WITH candidates AS (
                        SELECT id FROM public.monitoring_history
                        WHERE endpoint_id = %s AND checked_at < %s
                        ORDER BY checked_at, id LIMIT %s FOR UPDATE SKIP LOCKED
                    )
                    DELETE FROM public.monitoring_history AS history
                    USING candidates WHERE history.id = candidates.id""",
                        (next_endpoint, cutoff, plan.batch_size),
                    )
                    count = cursor.rowcount
            if count:
                deleted += count
                batches += 1
                if batches < plan.max_batches:
                    pause(.05)
            else:
                # A later run can pick up rows that were locked when this run visited the endpoint.
                endpoint = next_endpoint

        return {"mode": "apply", "cutoff": cutoff.isoformat(), "deleted": deleted,
                "batches": batches, "batch_limit_reached": batches == plan.max_batches}
    finally:
        if acquired:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (RETENTION_LOCK,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-batches", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database")
    options = parser.parse_args()
    enabled = os.environ.get("MONITORING_RETENTION_ENABLED", "").casefold() == "true"
    plan = RetentionPlan(options.database, options.days, options.batch_size, options.max_batches,
                         options.apply, options.confirm_database)
    try:
        plan.validate(enabled)
        parameters = {"dbname": options.database, "host": options.host, "port": options.port, "connect_timeout": 5}
        if options.user:
            parameters["user"] = options.user
        with closing(psycopg2.connect(**parameters)) as connection:
            summary = run_retention(connection, plan, enabled=enabled)
    except RetentionRefused as error:
        parser.exit(2, f"{error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "History maintenance interrupted. Earlier committed batches are preserved.\n")
    except psycopg2.Error:
        parser.exit(1, "History maintenance stopped because a database operation failed. Earlier committed batches are preserved.\n")
    print("History maintenance " + " ".join(f"{key}={value}" for key, value in summary.items()))


if __name__ == "__main__":
    main()
