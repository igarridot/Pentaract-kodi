#!/usr/bin/env python3
"""Raise Kodi's HTTP timeouts in an advancedsettings.xml (used by the local docker Kodi).

The addon exposes the same change from its root menu ("Fix Kodi HTTP timeouts
for streaming"); both paths share resources/lib/advancedsettings.py.
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "plugin.video.pentaract"))

from resources.lib.advancedsettings import (  # noqa: E402
    DEFAULT_CLIENT_TIMEOUT_SECONDS,
    DEFAULT_LOW_SPEED_TIME_SECONDS,
    tune_network_timeouts,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Adjust Kodi advancedsettings.xml network timeouts.")
    parser.add_argument("--file", required=True, help="Path to advancedsettings.xml")
    parser.add_argument("--client-timeout", type=int, default=DEFAULT_CLIENT_TIMEOUT_SECONDS, help="Value for curlclienttimeout")
    parser.add_argument("--low-speed-time", type=int, default=DEFAULT_LOW_SPEED_TIME_SECONDS, help="Value for curllowspeedtime")
    return parser.parse_args()


def main():
    args = parse_args()
    settings_path = os.path.abspath(args.file)
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)

    current = ""
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as handle:
            current = handle.read()

    with open(settings_path, "w", encoding="utf-8") as handle:
        handle.write(tune_network_timeouts(current, args.client_timeout, args.low_speed_time))
    print(
        "Updated %s: curlclienttimeout=%s curllowspeedtime=%s"
        % (settings_path, args.client_timeout, args.low_speed_time)
    )


if __name__ == "__main__":
    main()
