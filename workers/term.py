"""Shared terminal styling for TrackIST workers."""
import datetime
import sys

# Windows consoles default to a legacy code page (cp1254 on Turkish systems)
# that can't encode the box-drawing/arrow characters used below — crash on
# the very first banner. Force UTF-8, degrade gracefully where impossible.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

R   = "\033[0m"
B   = "\033[1m"
DIM = "\033[2m"
GR  = "\033[32m"
YL  = "\033[33m"
BL  = "\033[34m"
CY  = "\033[36m"
RD  = "\033[31m"
GY  = "\033[90m"
WH  = "\033[97m"


def _ts():
    return f"{GY}{datetime.datetime.utcnow().strftime('%H:%M:%S')}{R}"


def banner(title, subtitle, *details):
    line = f"{CY}{'─' * 52}{R}"
    print(f"\n{line}")
    print(f"  {B}{WH}{title}{R}")
    if subtitle:
        print(f"  {DIM}{subtitle}{R}")
    for d in details:
        print(f"  {GY}{d}{R}")
    print(f"{line}\n")


def ok(tag, msg):
    print(f"  {_ts()}  {GR}✓{R}  {B}{tag:<12}{R}  {msg}")


def info(tag, msg):
    print(f"  {_ts()}  {BL}·{R}  {B}{tag:<12}{R}  {msg}")


def warn(tag, msg):
    print(f"  {_ts()}  {YL}⚠{R}  {B}{tag:<12}{R}  {msg}")


def err(tag, msg):
    print(f"  {_ts()}  {RD}✗{R}  {B}{tag:<12}{R}  {msg}")
