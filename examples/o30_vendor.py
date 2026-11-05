"""O30 HOP standard CAN FD example using the modern SDK and vendor adapter.

No movement is requested. Supply the real side, HOP address, device/channel and library.
Run from the source tree with PYTHONPATH=python, or use `hand-tools.py read force`.
"""
import argparse
import json
from hand_tools.client import Bridge, default_bridge

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bridge", default=default_bridge())
parser.add_argument("--library", required=True)
parser.add_argument("--side", choices=["left", "right"], required=True)
parser.add_argument("--address", default="0x001")
parser.add_argument("--device", default="0")
parser.add_argument("--native-channel", default="0")
args = parser.parse_args()
config = vars(args).copy()
config.pop("bridge")
config["native-channel"] = config.pop("native_channel")
config.update(sdk="modern", model="O30", backend="minicanfd")
with Bridge(args.bridge, config) as hand:
    print(json.dumps(hand.meta, indent=2))
    print(json.dumps(hand.request("read", "position"), indent=2))
    print(json.dumps(hand.request("read", "force"), indent=2))
