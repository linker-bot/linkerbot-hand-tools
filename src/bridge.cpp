#include "hand_tools/backend.hpp"
#include <iostream>
#include <limits>
#include <locale>

namespace tools {
class Simulated final:public Backend {
    Config config_;
    std::vector<double> position_;
    std::vector<Control> controls_;
public:
    explicit Simulated(Config config):config_(std::move(config)),position_(profile(config_.model).legacy_size,0) {
        // Simulation uses an explicitly labelled normalized profile, not hardware capability evidence.
        controls_.push_back({"position","simulated 0-255",std::vector<std::vector<double>>(position_.size(),{0,255})});
    }
    std::string meta() const override {
        return object({{"model",json(config_.model)},{"sdk",json("simulation")},{"simulated","true"},
            {"identity",json("offline simulator")},{"controls",controls_json(controls_)},
            {"readable",json(std::vector<std::string>{"position","force","palm","temperature","fault"})},
            {"operations","[]"}});
    }
    std::string read(const std::string& name) override {
        if(name=="position") return object({{"raw",json(position_)},{"valid","true"},{"origin",json("simulation")}});
        if(name=="temperature" || name=="fault") return object({{"raw",json(std::vector<double>(position_.size(),0))},{"origin",json("simulation")}});
        if(name=="force" || name=="palm") return object({{"matrices", "["+object({{"name",json(name)},{"raw",json(std::vector<std::vector<double>>{{0,20,40},{60,80,100}})}})+"]"},{"origin",json("simulation")}});
        throw std::invalid_argument("unsupported simulated reading");
    }
    std::string write(const std::string& name,const std::vector<double>& values) override {
        if(name!="position") throw std::invalid_argument("unsupported simulated command");
        check_values(controls_[0],values); position_=values; return object({{"stage",json("simulated")}});
    }
    std::string operation(const std::string&) override { throw std::invalid_argument("no simulated device operations"); }
    void close() override {}
};
std::unique_ptr<Backend> make_backend(Config config) {
    config.model=canonical(config.model); validate(config);
    if(config.simulate) return std::make_unique<Simulated>(config);
    if(config.channel.empty() && (config.comm=="modbus" || config.backend!="minicanfd")) throw std::invalid_argument("an explicit channel/serial port is required");
    if(selected_sdk(config)=="modern") {
#ifdef HAND_TOOLS_MODERN
        return make_modern(config);
#else
        throw std::runtime_error("modern SDK was not enabled at build time");
#endif
    }
#ifdef HAND_TOOLS_LEGACY
    return make_legacy(config);
#else
    throw std::runtime_error("legacy SDK was not enabled at build time");
#endif
}
static uint32_t unsigned_value(const std::string& text) {
    if(text.empty() || text.front()=='-') throw std::invalid_argument("expected unsigned integer");
    size_t end=0; const auto value=std::stoull(text,&end,0);
    if(end!=text.size() || value>std::numeric_limits<uint32_t>::max()) throw std::invalid_argument("invalid unsigned integer");
    return static_cast<uint32_t>(value);
}
}
int main(int argc,char** argv) try {
    using namespace tools;
    std::locale::global(std::locale::classic());
    Config config;
    bool list=false;
    for(int i=1;i<argc;++i) {
        const std::string option=argv[i];
        if(option=="--simulate") { config.simulate=true; continue; }
        if(option=="--list") { list=true; continue; }
        if(option=="--help") {
            std::cout<<"hand_bridge --model MODEL --sdk auto|modern|legacy --side left|right\n"
                "  --backend socketcan|pcan|minicanfd|slcan --channel ENDPOINT\n"
                "  --comm can|canfd|modbus --library PATH --address ID --host ID\n"
                "  --device N --native-channel N --bitrate N --data-bitrate N\n"
                "  --serial-baud N --parity N|E|O --slcan-protocol lawicel-classic|canable-fd\n"
                "  --list (no I/O) | --simulate (offline only)\n";return 0;
        }
        if(++i>=argc) throw std::invalid_argument("missing option value: "+option);
        const std::string value=argv[i];
        if(option=="--model") config.model=canonical(value);
        else if(option=="--sdk") config.sdk=value;
        else if(option=="--side") config.side=value;
        else if(option=="--backend") config.backend=value;
        else if(option=="--channel") config.channel=value;
        else if(option=="--comm") config.comm=value;
        else if(option=="--library") config.library=value;
        else if(option=="--slcan-protocol") config.slcan_protocol=value;
        else if(option=="--parity" && value.size()==1) config.parity=value[0];
        else if(option=="--address") config.address=unsigned_value(value);
        else if(option=="--host") config.host=unsigned_value(value);
        else if(option=="--device") config.device=unsigned_value(value);
        else if(option=="--native-channel") config.native_channel=unsigned_value(value);
        else if(option=="--bitrate") config.bitrate=unsigned_value(value);
        else if(option=="--data-bitrate") config.data_bitrate=unsigned_value(value);
        else if(option=="--serial-baud") config.serial_baud=unsigned_value(value);
        else throw std::invalid_argument("unknown option: "+option);
    }
    if(list) {
        std::string models="["; for(const auto& p:profiles()) {if(models.size()>1)models+=',';models+=object({{"model",json(p.name)},{"preferred_sdk",json(p.modern?"modern":"legacy")},{"legacy_compatibility","true"}});}models+=']';
        std::cout<<object({{"models",models},
#ifdef HAND_TOOLS_MODERN
            {"modern","true"},
#else
            {"modern","false"},
#endif
#ifdef HAND_TOOLS_LEGACY
            {"legacy","true"}
#else
            {"legacy","false"}
#endif
        })<<'\n';return 0;
    }
    auto backend=make_backend(config);
    auto emit=[](const std::string& message){std::cout<<"HAND_TOOLS "<<message<<std::endl;};
    emit(object({{"event",json("ready")},{"meta",backend->meta()}}));
    std::string line;
    while(std::getline(std::cin,line)) {
        if(line.size()>65536) {std::cerr<<"request too large\n";break;}
        std::istringstream input(line); uint64_t id=0;std::string action,name;
        if(!(input>>id>>action)) continue;
        if(action=="close") break;
        try {
            std::string result;
            if(action=="meta") result=backend->meta();
            else {
                if(!(input>>name)) throw std::invalid_argument("missing channel");
                if(action=="read") result=backend->read(name);
                else if(action=="operation") result=backend->operation(name);
                else if(action=="write") {
                    std::vector<double> values;double value;
                    while(input>>value) {if(values.size()>=256)throw std::invalid_argument("too many values");values.push_back(value);}
                    if(!input.eof())throw std::invalid_argument("invalid numeric value");
                    result=backend->write(name,values);
                } else throw std::invalid_argument("unknown action");
            }
            emit(object({{"id",json(id)},{"ok","true"},{"data",result}}));
        }catch(const std::exception& error){emit(object({{"id",json(id)},{"ok","false"},{"error",json(error.what())}}));}
    }
    backend->close();return 0;
} catch(const std::exception& error) { std::cerr<<error.what()<<'\n';return 1; }
