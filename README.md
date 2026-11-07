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

- [Legacy SDK](https://github.com/linker-bot/linkerbot-hand-legacy-cpp-sdk): `c162cea9e89062b0f0e22dba98c19fe12f1f76bf` (SDK-only package).
- Modern SDK v0.3.3: `f88198c770190b5e29aa2d2f8b443f027fee54ff`.
- Transport v0.3.4: `0e190032d65ed0b315337b45b3779cf4f650ed68`.

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
source directories. Modern builds require hand SDK 0.3.3 or newer in the 0.3 minor
line; either SDK adapter requires transport 0.3.4 or newer in that minor line.
Rebuild tools and adapters with matching headers and libraries. No new physical
hardware, firmware/driver, timing or device-soak acceptance is claimed by this update.
The legacy package must include its maintained callback adapter
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

## Teaching controls and live inspection

The current Web UI has one range-aware slider and numeric editor per advertised control
channel. Slider edits and pasted vectors are **drafts**. Only **Write** submits the complete
vector; connecting, viewing telemetry, copying a reading or changing read rates never sends
position, speed, torque or enable commands. Draft midpoints are not measured device values.
Real readings appear beside each editor and in a joint monitor table. Vector indices are
channel indices; historical speed/torque vectors may have a different layout from position.
Unsupported controls and operations are not synthesized by the UI. Modern current limits
are not presented as torque controls.

The server maintains one read-only telemetry worker per connection, shared by all Web
clients. `/api/state` returns channel samples, SDK metadata, tool receipt age and requested
rates. `/api/rates` accepts a non-empty object such as `{"position":10,"force":30,"palm":5}`.
Rates are 0–100 Hz; 0 pauses that channel. Updates are validated atomically. Physical reads
remain serialized by Bridge; slow reads skip missed periods instead of accumulating work.
Requested rates do not guarantee device sample rates. Defaults are position 10 Hz,
speed/torque/current 5 Hz, force 10 Hz, palm 5 Hz, temperature/fault 1 Hz (only advertised
channels are polled). These rates persist for the connection, not across reconnects.

Finger and palm heatmaps are shown together where available. The wave chart holds the last
180 successful new samples per matrix, using actual receipt times. Each curve is the sum
of finite raw matrix elements, **not calibrated total force**. SDK-invalid or stale samples
and failed reads do not add points. Heatmap scales are per-frame automatic scales;
compare the numeric captions rather than interpreting color as an absolute physical value.
Read errors retain the previous sample with its original receipt age and an error label.
No missing Legacy freshness metadata is inferred. Reconnecting clears old trends and drafts.

### Full-screen TUI

In an interactive terminal, the existing `tui` command now opens an ANSI full-screen
inspector. It uses the same Bridge and read-only Monitor as HTTP, with no extra Python
packages. L30 and O30 use the advertised runtime control ranges and channel counts; the
UI does not reuse the historical 0–255 layouts for Modern hardware.

```sh
python3 hand-tools.py tui --simulate --model L30
python3 hand-tools.py tui --simulate --model O30
python3 hand-tools.py tui --model O30 --sdk modern --backend minicanfd \
  --device 0 --native-channel 0 --side right --address 0x001 --library /path/to/libcanbus.so
```

- **Tab** cycles Monitor, Controls, Tactile and Identity.
- **Arrow keys / Page Up / Page Down** scroll the current view (left/right for wide tables).
- Type a command and press **Enter**: `read force`, `rate force 30`, `rate palm 0`, `pause`,
  `write position VALUES...` or `operation enable` (only if advertised).
- **Escape** clears an unfinished command; **q** with an empty command line exits.
- **Ctrl+C** exits and restores terminal mode and cursor visibility. Closing is not an
  emergency stop and does not imply disable or mechanical arrival.

Use `tui --plain` for the original line terminal. Redirected input/output also selects the
line terminal automatically. The historical `v221_hand_tui` remains unchanged and opt-in.

### Tests

`ctest --test-dir build --output-on-failure` runs offline process/HTTP tests, read-only
scheduler and full-screen contracts, and (when Node.js 18+ is installed) browser-handler
unit tests without npm dependencies. CI installs Node.js 22. POSIX tests also start both
L30 and O30 in real pseudo-terminals and check alternate-screen entry/exit; Windows console
mode still requires manual platform acceptance. Fake-Bridge tests verify independent rates,
slow reads, failures, and that rendering/rate edits cause no writes. These tests are not
hardware acceptance and do not claim actual L30/O30 sensor dimensions or timing.
