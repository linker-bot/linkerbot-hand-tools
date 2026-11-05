#pragma once
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace tools {
inline std::string quote(const std::string& text) {
    std::ostringstream out; out << '"';
    for (unsigned char c : text) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c) << std::dec;
        else out << c;
    }
    return out.str() + '"';
}
inline std::string json(const std::string& value) { return quote(value); }
inline std::string json(const char* value) { return quote(value); }
inline std::string json(bool value) { return value ? "true" : "false"; }
template<class Number> std::string json(Number value) {
    if (!std::isfinite(double(value))) return "null";
    std::ostringstream out; out << std::setprecision(17) << +value; return out.str();
}
template<class T> std::string json(const std::vector<T>& values) {
    std::string out="["; bool first=true;
    for (const auto& value:values) { if (!first) out+=','; first=false; out+=json(value); }
    return out+']';
}
inline std::string object(const std::vector<std::pair<std::string,std::string>>& fields) {
    std::string out="{"; bool first=true;
    for (const auto& field:fields) { if (!first) out+=','; first=false; out+=quote(field.first)+':'+field.second; }
    return out+'}';
}
struct Config {
    std::string sdk="auto", model="L7", side="left", backend="socketcan", channel;
    std::string library, comm="", slcan_protocol="lawicel-classic";
    uint32_t bitrate=1000000, data_bitrate=5000000, serial_baud=115200;
    uint32_t device=0, native_channel=0;
    int64_t address=-1, host=-1;
    char parity='N';
    bool simulate=false;
};
struct Profile { const char* name; bool modern; int legacy_size; bool fd; };
inline const std::vector<Profile>& profiles() {
    static const std::vector<Profile> values{{"L6",true,6,false},{"O6",true,6,false},
        {"L7",false,7,false},{"L20_LITE",true,10,false},{"L20",true,20,false},
        {"L20_10",false,16,false},{"L21",false,25,false},{"L25",false,25,false},
        {"O20",false,16,true},{"L30",true,17,true},{"O30",true,20,true}};
    return values;
}
inline std::string canonical(std::string model) {
    for (auto& c:model) if (c>='a' && c<='z') c=char(c-'a'+'A');
    if (model=="G20" || model=="L20_11") return "L20_10";
    if (model=="L10" || model=="L20LITE") return "L20_LITE";
    return model;
}
inline const Profile& profile(const std::string& model) {
    for (const auto& p:profiles()) if (model==p.name) return p;
    throw std::invalid_argument("unknown model: "+model);
}
inline std::string selected_sdk(const Config& c) {
    if (c.sdk=="auto") return profile(c.model).modern ? "modern" : "legacy";
    if (c.sdk!="modern" && c.sdk!="legacy") throw std::invalid_argument("sdk must be auto, modern or legacy");
    if (c.sdk=="modern" && !profile(c.model).modern) throw std::invalid_argument("model is not implemented by modern SDK");
    return c.sdk;
}
inline void validate(const Config& c) {
    profile(c.model); (void)selected_sdk(c);
    if(c.side!="left" && c.side!="right") throw std::invalid_argument("side must be left or right");
    if(c.backend!="socketcan" && c.backend!="pcan" && c.backend!="minicanfd" && c.backend!="slcan")
        throw std::invalid_argument("unknown backend");
    if(c.comm!="" && c.comm!="can" && c.comm!="canfd" && c.comm!="modbus") throw std::invalid_argument("unknown communication mode");
    if(c.comm=="modbus" && (selected_sdk(c)!="legacy" || (c.model!="L7" && c.model!="O6" && c.model!="L20_LITE")))
        throw std::invalid_argument("Modbus requires explicit legacy SDK and L7, O6 or L20_LITE");
    if(c.backend=="minicanfd" && c.comm!="modbus" && !c.channel.empty())
        throw std::invalid_argument("MiniCANFD uses --device and --native-channel, not --channel");
    if(c.comm=="canfd" && !profile(c.model).fd) throw std::invalid_argument("this model profile uses Classic CAN");
    if(c.comm=="can" && profile(c.model).fd) throw std::invalid_argument("this model profile requires CAN FD");
    if(c.parity!='N' && c.parity!='E' && c.parity!='O') throw std::invalid_argument("parity must be N, E or O");
    if(c.address>0x1fffffff || c.address < -1 || c.host>255 || c.host < -1) throw std::invalid_argument("invalid device or host address");
}
struct Control {
    std::string name, unit;
    std::vector<std::vector<double>> ranges;
    std::string serialize() const { return object({{"name",json(name)},{"unit",json(unit)},{"ranges",json(ranges)}}); }
};
inline std::string controls_json(const std::vector<Control>& controls) {
    std::string out="["; for(size_t i=0;i<controls.size();++i) { if(i) out+=','; out+=controls[i].serialize(); } return out+']';
}
inline void check_values(const Control& control,const std::vector<double>& values) {
    if(values.size()!=control.ranges.size()) throw std::invalid_argument("wrong vector length for "+control.name);
    for(size_t i=0;i<values.size();++i) if(!std::isfinite(values[i]) || values[i]<control.ranges[i][0] || values[i]>control.ranges[i][1])
        throw std::invalid_argument("value outside advertised range");
}
class Backend {
public:
    virtual ~Backend()=default;
    virtual std::string meta() const=0;
    virtual std::string read(const std::string& channel)=0;
    virtual std::string write(const std::string& channel,const std::vector<double>& values)=0;
    virtual std::string operation(const std::string& name)=0;
    virtual void close()=0;
};
std::unique_ptr<Backend> make_backend(Config config);
#ifdef HAND_TOOLS_MODERN
std::unique_ptr<Backend> make_modern(const Config& config);
#endif
#ifdef HAND_TOOLS_LEGACY
std::unique_ptr<Backend> make_legacy(const Config& config);
#endif
} // namespace tools
