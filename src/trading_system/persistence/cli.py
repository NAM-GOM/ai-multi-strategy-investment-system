import asyncio
import json
import logging
from pathlib import Path

from trading_system.persistence.collector import Collector
from trading_system.persistence.config import PersistenceConfig
from trading_system.persistence.repository import (
    MarketRepository,
    backup_database,
    restore_database,
)
from trading_system.persistence.store import MarketStore, PersistenceError

logger = logging.getLogger("trading_system.persistence.cli")


def run_database_cli(args):
    try:
        config = PersistenceConfig(
            db_path=args.db_path,
            bootstrap_days=args.bootstrap_days,
            snapshot_seconds=args.snapshot_seconds,
            retention_days=args.retention_days,
            recovery_max_days=args.recovery_max_days,
        )
        if args.command == "db-init":
            with MarketStore(config.db_path):
                pass
            print(
                "Database initialized. Schema version: 1; WAL / FULL / busy_timeout=5000 / FK=ON."
            )
            return 0
        if args.command in ("db-backup", "db-restore"):
            if not args.backup_path:
                raise ValueError("Backup path is required.")
            if args.command == "db-backup":
                backup_database(config.db_path, args.backup_path)
            else:
                restore_database(args.backup_path, config.db_path)
            print(
                "SQLite Backup API operation: PASS. Integrity checked; "
                "existing file not overwritten."
            )
            return 0
        if args.command in ("db-status", "db-verify"):
            with MarketRepository(config.db_path) as repository:
                result = (
                    repository.summary() if args.command == "db-status" else repository.verify()
                )
            print(json.dumps(result, indent=2))
            return 0 if args.command == "db-status" or result["data_status"] == "COMPLETE" else 1
        if args.command == "collect":
            duration = 600 if args.duration is None else args.duration
            report = asyncio.run(Collector(config).run(duration))
            print(json.dumps(report, indent=2))
            if args.report_file:
                with Path(args.report_file).open("x", encoding="utf-8") as stream:
                    json.dump(report, stream, indent=2)
                    stream.write("\n")
            return (
                0
                if report["status"] == "COMPLETED"
                else 130
                if report["status"] == "INTERRUPTED"
                else 1
            )
        raise ValueError("Unsupported database command.")
    except KeyboardInterrupt:
        logger.info("collection interrupted; cleanup completed")
        return 130
    except PersistenceError as error:
        logger.error("PERSISTENCE_FAILURE category=%s", error.kind)
        print(f"PERSISTENCE_FAILURE: {error.kind}. Data was not reported as successfully stored.")
        return 1
    except ValueError:
        print("Invalid persistence settings. Check documented paths, ranges and command options.")
        return 2
    except OSError:
        print("Local file operation failed. Existing report/backup files are preserved.")
        return 2
    except Exception as error:
        logger.error("persistence command failed category=%s", type(error).__name__)
        print("Persistence command failed; details omitted. Check safe logs/app.log categories.")
        return 1
