# LinkerBot Hand Tools

Shared Demo, terminal and Web tools for the modern and legacy LinkerBot hand SDKs.
The SDK repositories own device protocols and their minimal integration examples.
This repository owns interactive controls, telemetry presentation and historical tool migration.

## Device routing

The preferred backend is the modern SDK for L6, O6, L20 Lite, L20, L30 and O30, and the
legacy SDK for L7, L20_10/L20_11 (`G20`), L21, L25 and O20. `L10` aliases L20 Lite.
Use `--sdk legacy` explicitly for a historical API path, such as O6/L20 Lite Modbus or
legacy palm sensing. A failed connection never switches SDK or replays a command.
Actual support depends on firmware, sensor and adapter; see [coverage](docs/migration.md).

## Build and try offline

CMake 3.16+, a C++17 compiler and Python 3 are required. No Python packages are needed.

```sh
cmake -S . -B build
cmake --build build --config Release --parallel 4
ctest --test-dir build -C Release --output-on-failure
python3 hand-tools.py models
python3 hand-tools.py read force --simulate --model O30
python3 hand-tools.py tui --simulate --model L7
python3 hand-tools.py web
```

Open `http://127.0.0.1:8080/`, choose **Offline simulation** and connect. Simulation is
labelled in the UI and runs in a separate executable that does not link either SDK or any vendor runtime. It is not hardware acceptance.
The terminal supports `info`, `read CHANNEL`, `write CHANNEL VALUES`, `operation NAME`
and `watch CHANNEL`. The Web UI shares the same serialized backend and displays tactile
matrices, palm data when available, metadata and downloadable readings.

## Build with both SDKs

Check out the three dependencies separately. The pinned source revisions are:

- [Legacy SDK](https://github.com/linker-bot/linkerbot-hand-legacy-cpp-sdk): `d47c163418468739db5d8026a7ce37e43276395d` (SDK-only package).
- Modern SDK: `e6b54ef04e56612d2bc49161b8b8d51782a54f32`.
- Transport: `6f9bd515175090e3c8b78304ac3eee6868a0d037`.

```sh
cmake -S . -B build \
  -DHAND_TOOLS_MODERN=ON -DHAND_TOOLS_LEGACY=ON \
  -DHAND_TOOLS_MODERN_SOURCE_DIR=/path/to/linkerbot-hand-cpp-sdk \
  -DHAND_TOOLS_LEGACY_ROOT=/path/to/linkerbot-hand-legacy-cpp-sdk \
  -DHAND_TOOLS_TRANSPORT_SOURCE_DIR=/path/to/linkerbot-transport-cpp
cmake --build build --config Release --parallel 4
ctest --test-dir build -C Release --output-on-failure
```

An installed modern SDK/transport can be selected through `CMAKE_PREFIX_PATH` instead of
source directories. The legacy package must include its maintained callback adapter
headers; its SDK binaries remain version 2.2.1. The maintained package is named
`linkerhand-legacy-cpp-sdk` and exports `LinkerHand::linkerhand_legacy_cpp_sdk`.
Installation paths use `linkerhand-legacy-cpp-sdk`; prebuilt library filenames remain
`linkerhand_cpp_sdk.*`.
SDK options can be enabled independently.
Use Linux x86_64/ARM64 or Windows x64 with matching SDK libraries and compiler runtimes.
macOS supports only the dependency-free offline tool build.

## Connect and read

Configure SocketCAN externally using the actual nominal/data rates. No system interface
configuration or device probing is performed by the Python server before connection.

```sh
python3 hand-tools.py read position --model L7 --side left --channel can0
python3 hand-tools.py read force --model O30 --side right --channel can0 --address 0x001
python3 hand-tools.py read palm --sdk legacy --model O6 --side left --channel can0
python3 hand-tools.py read position --sdk legacy --model L7 --comm modbus --channel /dev/ttyUSB0 --serial-baud 115200 --parity N
```

For O30 vendor CAN FD (HOP standard frames, no BRS):

```sh
python3 hand-tools.py read force --model O30 --sdk modern --side right \
  --backend minicanfd --device 0 --native-channel 0 --address 0x001 \
  --library /absolute/path/to/libcanbus.so
```

Windows uses `--backend pcan --channel PCAN_USBBUS1`, or `--backend minicanfd` with the
matching `HCanbus.dll`. SLCAN takes an explicit port and firmware profile, for example
`--backend slcan --channel COM10 --slcan-protocol canable-fd` for a supported FD device.
The generic PCAN FD timing profile is 80 MHz / 1M / 5M; other timing requires extending
an explicit transport configuration, not assuming bitrate fields alone determine it.

## Historical examples and UI

The full v2.2.1 tool source set, including the original TUI, Web UI, pressure/palm reads,
L30 and O30 vendor/SocketCAN examples, is retained under [historical/v2.2.1](historical/v2.2.1/SOURCE.md).
Build compatible historical hardware examples with `-DHAND_TOOLS_HISTORICAL_EXAMPLES=ON`.
Targets use the `v221_` prefix, including `v221_hand_tui` and `v221_test_o30_canfd_0` when
the vendor/platform prerequisites are present. These examples may move hardware or set
parameters. CI builds them but never runs them against a physical device.

Use the shared tools for new work. Historical Web UI files are reference sources and
retain their original SDK assumptions; the current Web UI is `python/hand_tools/static`.
See [migration and acceptance](docs/migration.md), [architecture](docs/architecture.md)
and [connection examples](examples/o30_vendor.py).

## Installation and validation

`cmake --install build --config Release --prefix /desired/prefix` installs `hand_bridge`, `hand_simulator`,
`bin/hand-tools.py` and the Python application. Run `python3 /desired/prefix/bin/hand-tools.py models`.
SDK and adapter runtimes must remain available. The local Windows install stages required
legacy runtime DLLs; the repository does not vendor them.

Connections start without tool-issued movement targets or default speed/torque writes.
Controls use advertised raw ranges and units. Current limits and torque are separate
operations. A successful SDK dispatch/ACK does not establish mechanical arrival.
Legacy data freshness and physical units remain unknown where its API supplies no metadata.

The HTTP server binds loopback by default, has no user authentication and is intended for
local/trusted operation. Use `--listen` only for an explicitly trusted network. Requests are
serialized; a timed-out bridge is stopped and its commands are not retried automatically.

See [NOTICE](NOTICE) for upstream sources and license attribution.
