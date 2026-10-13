"""Check that an extra works when installed alone.

Run in CI after `pip install ".[EXTRA]"`, with PYTHONTZPATH="" so there's no
system time zone database: New York time must come from the extra's own
dependencies (tzdata).

    python scripts/check_extra.py cli|mcp
"""
import datetime
import sys

MODULES = {"cli": "nytgames.cli.app", "mcp": "nytgames.mcp_server"}


def main() -> None:
    extra = sys.argv[1]
    __import__(MODULES[extra])
    from nytgames.cli import dates

    # New York is UTC-4 in summer and UTC-5 in winter.
    summer = datetime.datetime(2025, 7, 1, 12, tzinfo=dates.NYT_TIMEZONE)
    winter = datetime.datetime(2025, 1, 1, 12, tzinfo=dates.NYT_TIMEZONE)
    assert summer.utcoffset() == datetime.timedelta(hours=-4), summer.utcoffset()
    assert winter.utcoffset() == datetime.timedelta(hours=-5), winter.utcoffset()
    print(f"{extra}: {MODULES[extra]} imports, today in New York is {dates.today()}")


if __name__ == "__main__":
    main()
