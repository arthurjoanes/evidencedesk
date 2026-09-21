import argparse
import json

from evidencedesk.retention.service import RetentionPolicy, sweep


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One bounded retention sweep for one explicitly selected tenant."
    )
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--temporary-hours", type=int, default=24)
    parser.add_argument("--progress-days", type=int, default=7)
    parser.add_argument("--audit-days", type=int, default=90)
    parser.add_argument("--batch-limit", type=int, default=100)
    parser.add_argument("--scan-limit", type=int, default=1000)
    args = parser.parse_args()
    try:
        policy = RetentionPolicy(
            args.temporary_hours,
            args.progress_days,
            args.audit_days,
            args.batch_limit,
            args.scan_limit,
        )
    except ValueError as error:
        parser.error(str(error))
    result = sweep(args.tenant, policy)
    print(json.dumps(result, ensure_ascii=False))
    if result["blocked_or_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
