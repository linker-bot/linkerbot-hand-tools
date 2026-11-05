# Tool and SDK boundaries

`hand_bridge` owns one selected SDK connection. Its request/response protocol is shared
by the CLI, terminal and HTTP server. All device requests are serialized; no UI implements
CAN frames, HOP fragmentation, RTU CRC, reply correlation or firmware-specific parsing.

Modern devices use `HandDevice` and runtime capabilities. Legacy devices use the prebuilt
`LinkerHandApi` with transport callbacks. The selected backend remains fixed for the whole
connection. Closing destroys the API before its callback owners and physical transport.

The modern adapter exports identity, SDK capabilities, raw control ranges, reading origin,
validity, age and generation. Tactile output preserves descriptors, sensor units, decoded
fields, raw bytes and matrix dimensions. Its command result records the SDK command stage;
a pending result is not a reason to resubmit. `read command` inspects the last command.

The legacy compatibility adapter retains historical model/vector layouts, including reserved
slots. These profiles describe old API usage, not verified mechanical behavior. Legacy
readings explicitly carry unknown freshness; the tool does not invent device timestamps,
physical units or acknowledgments. Legacy palm and aggregate reads remain available only
where historical interfaces exist. Unsupported operations raise a visible error.

Simulation has a separate backend with no SDK/driver calls. It exercises framing, alias
selection, validation, process lifetime, terminal commands, HTTP access and tactile rendering.
It does not simulate arbitration, physical timing or device firmware.

SDKs retain protocol codecs, connection primitives, public headers, focused protocol tests
and minimal consumer examples. Device control applications and historical demonstrations
belong here. SDK and tool versions are pinned independently and validated together.
