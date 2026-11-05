# Migration coverage and acceptance

The migration baseline is linkerhand-cpp-sdk v2.2.1. Original tool sources and image assets
are retained byte-for-byte with a source commit and hash manifest under historical/v2.2.1.
No SDK or vendor binary is copied into this repository.

| Historical feature | Current owner/path |
| --- | --- |
| Full model selection | Shared CLI, terminal and Web UI; preferred modern/legacy routing |
| L7, G20, L21, L25, O20 controls/readings | Legacy adapter |
| L6, O6, L20 Lite, L20, L30, O30 | Modern adapter; explicit legacy compatibility remains selectable |
| Finger tactile matrices | Both adapters; dynamic shape/metadata from the modern SDK |
| Palm pressure and G20 aggregate force | Explicit legacy adapter paths; not inferred from finger matrices |
| O30 vendor CAN FD, HOP standard frames | Modern O30 + MiniCANFD; v221_test_o30_canfd_0 preserves the original example |
| SocketCAN FD / PCAN / MiniCANFD / SLCAN | Shared transport configuration, subject to SDK/platform support |
| O6/L20 Lite/L7 historical Modbus | Explicit legacy SDK only; existing raw RTU backend, no transaction redesign |
| Original full-screen TUI and motion demos | Opt-in historical hardware example targets |
| Original Web UI implementation | Retained reference source; replaced by the shared current Web application |

The current terminal is a command-driven cross-platform interface, not a pixel-identical
port of the historical full-screen TUI. The current Web UI uses one vector editor per
advertised control rather than inheriting fixed per-model slider assumptions. No historical
pose is automatically applied; historical motion programs remain explicitly selected examples.

Ordinary L20 differs from G20: the modern L20 SDK uses 16 joints while the old tool profile
uses a 20-entry command layout with reserved slots. SDK routing is recorded with each
connection. Legacy 0-255 values are never treated as modern percentages or universal angles.

Do not interpret an SDK function declaration, compiled example or simulator as hardware
acceptance. Record model, firmware, side/address, adapter, driver, OS/compiler, dependency
commits and actual read/control results for each supported path. In particular, confirm
legacy parameter vector layouts, O20 firmware, tactile sensor descriptors/units, physical
arrival and Modbus timing. Hardware acceptance was not performed during extraction.

Future protocol changes belong in the relevant SDK. New interactive features and historical
compatibility demonstrations belong in this repository, with a matching device acceptance record.
