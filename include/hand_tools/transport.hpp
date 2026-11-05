#pragma once
#include "hand_tools/backend.hpp"
#include <linkerbot/can/transport.hpp>
#include <functional>
namespace tools {
using TransportFactory=std::function<std::unique_ptr<linkerbot::can::CANTransport>()>;
TransportFactory transport_factory(const Config& config);
}
