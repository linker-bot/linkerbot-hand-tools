#include "hand_tools/transport.hpp"
#include <linkerbot/hand/api/device.hpp>
#include <optional>
#include <algorithm>

namespace tools {
namespace h=linkerbot::hand;
static std::string origin(h::TelemetryValueOrigin v) {
    switch(v) {
    case h::TelemetryValueOrigin::kDeviceMeasured:return "device_measured";
    case h::TelemetryValueOrigin::kDeviceConfigured:return "device_configured";
    case h::TelemetryValueOrigin::kCommandCache:return "command_cache";
    case h::TelemetryValueOrigin::kDerived:return "derived";
    default:return "unknown";
    }
}
static std::string sample_meta(const h::SampleMeta& m) {
    return object({{"valid",json(m.valid)},{"stale",json(m.stale)},{"origin",json(origin(m.origin))},
        {"generation",json(m.connection_generation)},{"sequence",json(m.sequence)},
        {"age_ms",m.age?json(std::chrono::duration<double,std::milli>(*m.age).count()):"null"},
        {"within_declared_range",json(m.within_declared_range)}});
}
static std::string command_status(const h::CommandHandle& handle) {
    std::string stage;
    switch(handle.stage()) {
    case h::CommandStage::kAccepted:stage="accepted";break;
    case h::CommandStage::kDispatched:stage="dispatched";break;
    case h::CommandStage::kAcknowledged:stage="acknowledged";break;
    case h::CommandStage::kFailed:stage="failed";break;
    case h::CommandStage::kSuperseded:stage="superseded";break;
    case h::CommandStage::kCancelled:stage="cancelled";break;
    }
    std::string error="null";
    if(handle.error())try {std::rethrow_exception(handle.error());}catch(const std::exception& e){error=json(e.what());}
    return object({{"command_id",json(handle.command_id())},{"stage",json(stage)},
        {"done",json(handle.done())},{"sent_frames",json(handle.sent_frames())},{"error",error},
        {"mechanical_arrival_confirmed","false"}});
}
class Modern final:public Backend {
    Config config_;
    std::unique_ptr<h::HandDevice> hand_;
    h::DeviceCapabilities caps_;
    std::vector<Control> controls_;
    std::vector<std::string> readable_{"position","version","command"},operations_;
    std::optional<h::CommandHandle> last_command_;
    void control(const char* name,h::CommandSemantic semantic) {
        const auto* cap=caps_.command(semantic);if(!cap)return;
        Control c{name,cap->raw_unit?std::string(*cap->raw_unit):"raw count",{}};
        const auto count=cap->channels.empty()?caps_.joints.size():cap->channels.size();
        for(size_t i=0;i<count;++i) {
            const auto* range=cap->range_for(i);if(!range)return;
            c.ranges.push_back({range->minimum,range->maximum});
        }
        if(!c.ranges.empty())controls_.push_back(std::move(c));
    }
    template<class Sample>std::string vector_sample(const Sample& sample) {
        return object({{"raw",json(sample.raw)},{"meta",sample_meta(sample.meta)}});
    }
    std::string finish(h::CommandHandle handle) {
        last_command_=std::move(handle);
        (void)last_command_->wait_for(std::chrono::milliseconds{2000});
        return command_status(*last_command_);
    }
public:
    explicit Modern(const Config& config):config_(config) {
        h::HandDeviceConfig c;
        c.side=config.side=="left"?h::HandSide::kLeft:h::HandSide::kRight;
        if(config.model=="L6")c.model=h::Model::kL6;
        else if(config.model=="O6")c.model=h::Model::kO6;
        else if(config.model=="L20_LITE")c.model=h::Model::kL20Lite;
        else if(config.model=="L20")c.model=h::Model::kL20;
        else if(config.model=="L30")c.model=h::Model::kL30;
        else if(config.model=="O30")c.model=h::Model::kO30;
        else throw std::invalid_argument("model is not implemented by modern SDK");
        c.interface_name=config.backend+":"+config.channel;
        if(config.address>=0)c.address=static_cast<uint32_t>(config.address);
        if(config.host>=0)c.host_address=static_cast<uint32_t>(config.host);
        c.auto_start_periodic_reports=false;
        hand_=std::make_unique<h::HandDevice>(c,transport_factory(config));
        hand_->open();caps_=hand_->get_capabilities();
        control("position",h::CommandSemantic::kAngles);
        control("speed",h::CommandSemantic::kSpeeds);
        control("current_limit",h::CommandSemantic::kCurrentLimits);
        const std::vector<std::pair<const char*,h::TelemetrySemantic>> readings{
            {"speed",h::TelemetrySemantic::kMeasuredSpeeds},{"configured_speed",h::TelemetrySemantic::kConfiguredSpeeds},
            {"current",h::TelemetrySemantic::kCurrents},{"current_limit",h::TelemetrySemantic::kCurrentLimits},
            {"torque",h::TelemetrySemantic::kTorques},{"temperature",h::TelemetrySemantic::kTemperatures},
            {"fault",h::TelemetrySemantic::kFaults},{"force",h::TelemetrySemantic::kForce},
            {"voltage",h::TelemetrySemantic::kVoltages}};
        for(const auto& item:readings)if(caps_.supports(item.second))readable_.push_back(item.first);
        for(const auto& item:std::vector<std::pair<const char*,h::DeviceOperation>>{
            {"enable",h::DeviceOperation::kEnable},{"disable",h::DeviceOperation::kDisable},
            {"clear_faults",h::DeviceOperation::kClearFaults}})
            if(caps_.supports(item.second))operations_.push_back(item.first);
    }
    ~Modern() override {try{close();}catch(...) {}}
    std::string meta() const override {
        const auto identity=hand_->get_identity();
        return object({{"model",json(config_.model)},{"sdk",json("modern")},{"simulated","false"},
            {"identity",json(identity?identity->product_code.value_or("unreported"):"unreported")},
            {"firmware",json(identity?identity->firmware_version.value_or("unreported"):"unreported")},
            {"controls",controls_json(controls_)},{"readable",json(readable_)},{"operations",json(operations_)},
            {"sdk_capabilities",caps_.serialize()}});
    }
    std::string read(const std::string& name) override {
        if(name=="command") {if(!last_command_)throw std::invalid_argument("no command has been submitted");return command_status(*last_command_);}
        if(name=="version")return meta();
        if(std::find(readable_.begin(),readable_.end(),name)==readable_.end())throw std::invalid_argument("unsupported reading");
        if(name=="position")return vector_sample(hand_->get_angles());
        if(name=="speed")return vector_sample(hand_->get_speeds());
        if(name=="configured_speed")return vector_sample(hand_->get_configured_speeds());
        if(name=="current")return vector_sample(hand_->get_currents());
        if(name=="current_limit")return vector_sample(hand_->get_current_limits());
        if(name=="torque")return vector_sample(hand_->get_torques());
        if(name=="temperature")return vector_sample(hand_->get_temperatures());
        if(name=="voltage")return vector_sample(hand_->get_voltages());
        if(name=="fault")return vector_sample(hand_->get_faults());
        if(name=="force") {
            const auto sample=hand_->get_force();std::string matrices="[",sensors="[",fields="[";
            for(const auto& m:sample.tactile){if(matrices.size()>1)matrices+=',';matrices+=object({{"name",json(m.name)},{"rows",json(m.rows)},{"columns",json(m.columns)},{"raw",json(m.raw)}});}matrices+=']';
            for(const auto& sensor:sample.sensors) {
                if(sensors.size()>1)sensors+=',';
                std::string decoded="[";
                for(const auto& field:sensor.fields){if(decoded.size()>1)decoded+=',';decoded+=object({{"semantic",json(field.semantic)},{"encoding",json(field.encoding)},{"offset",json(field.offset)},{"count",json(field.count)},{"values",json(field.values)}});}decoded+=']';
                sensors+=object({{"name",json(sensor.sensor_name)},{"type",json(sensor.sensor_type)},
                    {"unit",json(sensor.data_unit)},{"descriptor",json(sensor.descriptor)},
                    {"rows",json(sensor.rows)},{"columns",json(sensor.columns)},{"available",json(sensor.available)},
                    {"raw_data",json(sensor.raw_data)},{"fields",decoded}});
            }sensors+=']';
            for(const auto& f:sample.fields) {
                if(fields.size()>1)fields+=',';
                std::string raw="[",units="[",encodings="[",validity="[";
                for(size_t i=0;i<f.raw.size();++i){if(i)raw+=',';raw+=f.raw[i]?json(*f.raw[i]):"null";}raw+=']';
                for(size_t i=0;i<f.units.size();++i){if(i)units+=',';units+=f.units[i]?json(*f.units[i]):"null";}units+=']';
                for(size_t i=0;i<f.encodings.size();++i){if(i)encodings+=',';encodings+=f.encodings[i]?json(*f.encodings[i]):"null";}encodings+=']';
                for(size_t i=0;i<f.valid_values.size();++i){if(i)validity+=',';if(!f.valid_values[i])validity+="null";else {validity+='[';for(size_t j=0;j<f.valid_values[i]->size();++j){if(j)validity+=',';validity+=json(bool((*f.valid_values[i])[j]));}validity+=']';}}validity+=']';
                fields+=object({{"name",json(f.name)},{"sensor_names",json(f.sensor_names)},{"raw",raw},{"units",units},{"encodings",encodings},{"valid_values",validity},{"meta",sample_meta(f.meta)}});
            }fields+=']';
            return object({{"raw",json(sample.raw)},{"shape",json(sample.shape)},{"matrices",matrices},
                {"sensors",sensors},{"fields",fields},{"unsupported_fields",json(sample.unsupported_fields)},{"meta",sample_meta(sample.meta)}});
        }
        throw std::invalid_argument("unsupported reading");
    }
    std::string write(const std::string& name,const std::vector<double>& values) override {
        const auto found=std::find_if(controls_.begin(),controls_.end(),[&](const auto& c){return c.name==name;});
        if(found==controls_.end())throw std::invalid_argument("unsupported control");check_values(*found,values);
        if(name=="position") {
            std::vector<int32_t> raw;for(double v:values){if(std::trunc(v)!=v)throw std::invalid_argument("positions require integer raw counts");raw.push_back(static_cast<int32_t>(v));}
            return finish(hand_->set_angles(raw));
        }
        if(name=="speed")return finish(hand_->set_speeds(values));
        if(name=="current_limit")return finish(hand_->set_current_limits(values));
        throw std::invalid_argument("unsupported control");
    }
    std::string operation(const std::string& name) override {
        if(std::find(operations_.begin(),operations_.end(),name)==operations_.end())throw std::invalid_argument("unsupported operation");
        if(name=="enable")return finish(hand_->enable());
        if(name=="disable")return finish(hand_->disable());
        return finish(hand_->clear_faults());
    }
    void close() override {if(hand_ && hand_->is_open())hand_->close();}
};
std::unique_ptr<Backend> make_modern(const Config& config){return std::make_unique<Modern>(config);}
}
