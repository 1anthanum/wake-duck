"""python -m wake_duck demo   - scripted walk-through on a fake system (touches nothing real)
python -m wake_duck --version"""
import argparse
import sys

from . import __version__


def main(argv=None):
    p = argparse.ArgumentParser(prog="wake-duck", description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version="wake-duck " + __version__)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("demo", help="print the scripted walk-through (fake clock, fake volume, fake apps)")
    args = p.parse_args(argv)
    if args.cmd == "demo":
        from .demo import run
        sys.stdout.write(run())
        return 0
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
