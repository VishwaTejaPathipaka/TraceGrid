# TraceGrid backup and recovery runbook

## Record the recovery point

Record the release commit, PostgreSQL major version, source database identity, committed Alembic revision, operator, backup time in UTC, and encrypted storage location. Agree on acceptable downtime and potential data loss before a rollout. A daily logical backup provides a recovery point up to a day old if the job succeeds. Verify that off-host archives and their retention fit the free hosting allowance. If a shorter recovery window is required, verify that point-in-time recovery is available within that allowance and rehearse it separately before rollout.

Use PostgreSQL 17 client tools with approved libpq service aliases and existing authentication. The examples use aliases assigned to the authorized source and an isolated restore target. Verify the address, port, database, role and revision before proceeding. For a pre-migration backup, pause application writers, scheduled workers and maintenance jobs so the recorded counts describe the same recovery point as the dump. Daily backups can use PostgreSQL's consistent snapshot while the service runs.

```sh
psql -X -w --dbname='service=tracegrid_backup' -v ON_ERROR_STOP=1 <<'SQL'
SELECT current_database(), current_user, inet_server_addr(), inet_server_port();
SHOW server_version;
SELECT version_num FROM alembic_version;
SELECT 'users' AS relation, count(*) FROM users
UNION ALL SELECT 'endpoints', count(*) FROM api_endpoints
UNION ALL SELECT 'history', count(*) FROM monitoring_history
UNION ALL SELECT 'incidents', count(*) FROM incidents
UNION ALL SELECT 'notifications', count(*) FROM incident_notifications
UNION ALL SELECT 'revocations', count(*) FROM revoked_tokens
UNION ALL SELECT 'account links', count(*) FROM account_tokens
UNION ALL SELECT 'rate counters', count(*) FROM rate_limit_counters;
SQL
```

The count query assumes the current schema. For an older revision, query the existing tables and record which later tables are absent.

## Back up, verify and store

Set `BACKUP_DIR` to an approved private directory outside Git. Dump with a role permitted to read the required tables and sequences. Verify the archive listing, checksum and a real restore. A checksum or archive listing alone does not establish recoverability.

```sh
set -eu
umask 077
run_dir="$(mktemp -d "$BACKUP_DIR/tracegrid-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
cd "$run_dir"
archive="tracegrid.dump"
pg_dump --no-password --dbname='service=tracegrid_backup' --format=custom --file="$archive"
pg_restore --list "$archive" >/dev/null
sha256sum "$archive" > "$archive.sha256"
sha256sum -c "$archive.sha256"
```

Send the archive and checksum to encrypted off-host storage using an identity scoped to the backup location. Restrict access to restore operators. These archives contain user data and account-security records. Retain pre-release recovery points separately from rotating daily backups, alert on failed or stale backups, and verify newly retrieved bytes against the trusted checksum. Back up role grants and connection configuration separately through the approved configuration and secret stores.

## Restore and rehearse

1. Obtain approval before using a backup containing real data. Use a fresh database on an isolated PostgreSQL 17 instance with a role that cannot reach the live instance. Prevent public ingress, email delivery and probe egress. Confirm the target identity with the identity query above and verify that its application schema is empty.
2. Restore an immutable backup copy after validating its checksum. Skip source ownership and ACLs, then use the reviewed target grants for the application.

   ```sh
   sha256sum -c "$archive.sha256"
   pg_restore --no-password --dbname='service=tracegrid_restore' \
     --single-transaction --exit-on-error --no-owner --no-privileges "$archive"
   ```

3. Compare the restored revision, table counts and sequence state with the recovery-point record. Check representative relationships and incident states privately. Share aggregates without exporting records or credentials.
4. Inject the isolated restore database URL through the approved migration identity. Apply the intended release revision with `python -m alembic upgrade 20261123_06` and confirm `python -m alembic current` plus the database's committed revision. Verify expected schema, indexes, post-migration counts and foreign keys. Check application startup with the intended runtime grants. Keep the clone in outbox mode and use a synthetic target for application smoke tests.
5. Record restore duration, preservation results and any gaps. Retire the isolated environment after the operator verifies its identity. Keep the recovery artifact available.

For any live migration, require a fresh verified backup, successful isolated rehearsal and **explicit approval**. Stop on an unexpected revision, migration error or data mismatch.

## Failure and rollback

Keep traffic in maintenance and stop writers if an upgrade or verification fails. Determine the committed schema and actual data state before a retry. For an application-only regression, revert to a known-good build when it was verified against the committed schema. For an incompatible schema or data failure, restore into a new verified database, reconcile writes after the recovery point or use rehearsed point-in-time recovery, and cut over only after validation and approval. Preserve the original database for investigation and run only one writer and worker fleet during cutover. Avoid an untested downgrade or restore over the live database. Review pending notifications before resuming external delivery because restores can replay eligible work.

## Rehearsal evidence

On 24 November 2026, a fresh loopback-only PostgreSQL 17 cluster held a synthetic source and a separate empty restore database. A 28,305-byte custom archive passed inspection and SHA-256 verification. Dump, inspection, and restore took under one second for the tiny fixture. The restored copy matched full row digests and the endpoint sequence. Alembic upgraded the copy from `20261123_05` to `20261123_06` and created the rate-limit expiry index.

The source and upgraded copy retained 1 user, 1 endpoint, 3 history rows, 1 incident and 1 notification. The restored app started and shut down its scheduler, PostgreSQL listener and outbox worker successfully. The off-host storage transfer, host-failure recovery, production-scale recovery time and provider point-in-time recovery remain to be verified on approved infrastructure.

[PostgreSQL 17 pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html) · [PostgreSQL 17 pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html)
