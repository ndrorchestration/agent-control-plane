"""Minimal transport-enabled Reticulum node for bounded localhost multi-hop tests."""

import argparse
import time

import RNS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    args = parser.parse_args()

    RNS.Reticulum(configdir=args.config_dir)
    while True:
        time.sleep(1.0)


if __name__ == "__main__":
    main()
