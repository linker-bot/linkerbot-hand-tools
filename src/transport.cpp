#include "hand_tools/transport.hpp"
#include <linkerbot/can/pcan_transport.hpp>
#include <linkerbot/can/vendor_canfd_transport.hpp>
#include <linkerbot/can/slcan_transport.hpp>
#ifdef __linux__
#include <linkerbot/can/socketcan_transport.hpp>
#endif
namespace tools {
TransportFactory transport_factory(const Config& c) {
    const bool fd=profile(c.model).fd;
    if(c.backend=="socketcan") {
#ifdef __linux__
        return [c,fd]{return std::make_unique<linkerbot::can::SocketCANTransport>(c.channel,fd);};
#else
        throw std::invalid_argument("SocketCAN requires Linux");
#endif
    }
    if(c.backend=="minicanfd") {
        if(!fd)throw std::invalid_argument("MiniCANFD profile requires a CAN FD model");
        linkerbot::can::VendorCanFdTransport::Config config;
        config.device_index=c.device;config.channel_index=c.native_channel;
        config.nom_baud=c.bitrate;config.dat_baud=c.data_bitrate;
        if(!c.library.empty())config.library_path=c.library;
        return [config]{return std::make_unique<linkerbot::can::VendorCanFdTransport>(config);};
    }
    if(c.backend=="pcan") {
        linkerbot::can::PcanConfig config;
        config.channel=linkerbot::can::pcan_channel_handle(c.channel);
        config.mode=fd?linkerbot::can::PcanMode::kFd:linkerbot::can::PcanMode::kClassic;
        config.nominal_bitrate=c.bitrate;config.data_bitrate=c.data_bitrate;
        if(!c.library.empty())config.library_path=c.library;
        return [config]{return std::make_unique<linkerbot::can::PcanTransport>(config);};
    }
    linkerbot::can::SlcanConfig config;
    config.port=c.channel;config.fd=fd;config.serial_baud=c.serial_baud;
    config.nominal_bitrate=c.bitrate;config.data_bitrate=c.data_bitrate;
    if(c.slcan_protocol=="canable-fd")config.protocol=linkerbot::can::SlcanProtocol::kCanableFd;
    else if(c.slcan_protocol!="lawicel-classic")throw std::invalid_argument("unknown SLCAN firmware protocol");
    return [config]{return std::make_unique<linkerbot::can::SlcanTransport>(config);};
}
}
