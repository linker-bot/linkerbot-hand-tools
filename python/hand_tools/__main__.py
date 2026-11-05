import argparse
import cmd
import json
import time

from .client import Bridge, catalogue, default_bridge
from .server import create_server


def display(value):
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


class Terminal(cmd.Cmd):
    intro = "Hand tools terminal. Use info, read CHANNEL, write CHANNEL VALUES, operation NAME, watch CHANNEL or quit."
    prompt = "hand-tools> "

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge

    def do_info(self, _):
        """Show the selected SDK, identity, capabilities and units."""
        display(self.bridge.meta)

    def do_read(self, name):
        """Read an advertised telemetry channel."""
        self.execute("read", name.strip())

    def do_write(self, text):
        """Write a complete advertised raw control vector: write position 1 2 ..."""
        try:
            parts = text.split()
            self.execute("write", parts[0], [float(v) for v in parts[1:]])
        except (ValueError, IndexError) as error:
            print(error)

    def do_operation(self, name):
        """Run an advertised discrete operation explicitly."""
        self.execute("operation", name.strip())

    def do_watch(self, name):
        """Read one channel repeatedly until Ctrl+C. Commands are never replayed."""
        try:
            while True:
                self.execute("read", name.strip())
                time.sleep(1)
        except KeyboardInterrupt:
            print()

    def execute(self, action, name, values=()):
        try:
            display(self.bridge.request(action, name, values))
        except (ValueError, RuntimeError, OSError) as error:
            print(error)

    def do_quit(self, _):
        return True

    do_EOF = do_quit


def main():
    parser = argparse.ArgumentParser(description="Shared modern and legacy hand tools")
    parser.add_argument("command", choices=["models", "info", "read", "write", "operation", "tui", "web"])
    parser.add_argument("arguments", nargs="*")
    parser.add_argument("--bridge", default=default_bridge())
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--simulate", action="store_true")
    for name, default in (("sdk", "auto"), ("model", "L7"), ("side", "left"), ("backend", "socketcan"),
                          ("channel", ""), ("comm", ""), ("library", ""), ("address", None), ("host", None),
                          ("device", None), ("native-channel", None), ("bitrate", None), ("data-bitrate", None),
                          ("serial-baud", None), ("parity", None), ("slcan-protocol", None)):
        parser.add_argument("--" + name, default=default)
    args = parser.parse_args()
    if args.command == "models":
        display(catalogue(args.bridge))
        return
    if args.command == "web":
        server = create_server(args.bridge, args.listen, args.port)
        print(f"Hand tools: http://{args.listen}:{server.server_port}/")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.manager.close()
            server.server_close()
        return
    config = {key.replace("_", "-"): value for key, value in vars(args).items()
              if key not in {"command", "arguments", "bridge", "listen", "port"} and value is not None}
    with Bridge(args.bridge, config) as bridge:
        if args.command == "tui":
            Terminal(bridge).cmdloop()
        elif args.command == "info":
            display(bridge.meta)
        else:
            if not args.arguments:
                parser.error("A channel or operation name is required")
            values = [float(value) for value in args.arguments[1:]] if args.command == "write" else []
            display(bridge.request(args.command, args.arguments[0], values))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        raise SystemExit(str(error))
