#include "hand_tools/transport.hpp"
#include "LinkerHandApi.h"
#include "communication/Modbus.h"
#include "legacy/CanCallbacks.h"
#include "legacy/ModbusCallbacks.h"
#include <algorithm>

namespace tools {
class Legacy final:public Backend {
    Config config_;
    std::shared_ptr<linkerbot::can::CANDispatcher> dispatcher_;
    std::shared_ptr<linkerhand::legacy::CanCallbacks> callbacks_;
    std::shared_ptr<Modbus> modbus_;
    // Keep every callback owner alive until the prebuilt API is destroyed.
    std::unique_ptr<LinkerHandApi> hand_;
    std::vector<Control> controls_;
    std::vector<std::string> readable_{"position","speed","torque","temperature","fault","force","version"},operations_;
    bool raw_=false;
    int size_=0;
    template<class T>std::string reading(const T& values) {
        return object({{"raw",json(values)},{"meta",object({{"valid","null"},{"stale","null"},{"origin",json("legacy_unspecified")},{"freshness",json("unknown")}})}});
    }
public:
    explicit Legacy(const Config& config):config_(config) {
        const std::vector<std::pair<std::string,LINKER_HAND>> models{{"L6",L6},{"O6",O6},{"L7",L7},{"L20_LITE",L10},
            {"L20",L20},{"L20_10",G20},{"L21",L21},{"L25",L25},{"O20",O20},{"L30",L30},{"O30",O30}};
        const auto model=std::find_if(models.begin(),models.end(),[&](const auto& item){return item.first==config.model;});
        if(model==models.end())throw std::invalid_argument("unknown legacy model");
        const auto side=config.side=="left"?LEFT:RIGHT;
        if(config.address>=0 || config.host>=0)throw std::invalid_argument("legacy SDK has no public address override; use its firmware defaults");
        if(config.comm=="modbus")modbus_=std::make_shared<Modbus>(config.channel,int(config.serial_baud),config.parity);
        else {
            dispatcher_=std::make_shared<linkerbot::can::CANDispatcher>(transport_factory(config)());
            const bool fd=profile(config.model).fd;
            callbacks_=std::make_shared<linkerhand::legacy::CanCallbacks>(dispatcher_,fd,fd && config.model!="O30");
        }
        hand_=std::make_unique<LinkerHandApi>(model->second,side,config.comm=="modbus"?COMM_TYPE::MODBUS:COMM_TYPE::CAN);
        if(modbus_) {
            if(!modbus_->isOpen())throw std::runtime_error("serial port did not open");
            (void)linkerhand::legacy::bind_modbus_callbacks(*hand_,modbus_);
        } else {
            auto owner=callbacks_;
            hand_->setCanTxCallback([owner](uint32_t id,const uint8_t* data,uintptr_t size){return owner->transmit(id,data,size);});
            hand_->setCanRxCallback([owner](uint32_t* id,uint8_t* data,uint8_t* size){return owner->receive(id,data,size);});
        }
        size_=profile(config.model).legacy_size;
        Control position{"position","legacy 0-255",std::vector<std::vector<double>>(size_,{0,255})};
        if(config.model=="L30") {
            const auto ranges=hand_->getPositionRangeRaw();
            if(ranges.size()!=static_cast<size_t>(size_))throw std::runtime_error("legacy raw position layout unavailable");
            raw_=true;position.unit="legacy raw count";position.ranges.clear();
            for(const auto& range:ranges)position.ranges.push_back({double(range.first),double(range.second)});
        }
        controls_.push_back(position);
        const int parameters=(config.model=="L20" || config.model=="L20_10")?5:size_;
        for(const auto* name:{"speed","torque"}) {
            Control c{name,"legacy raw count",std::vector<std::vector<double>>(parameters,{0,255})};
            if(raw_) {
                auto range=std::string(name)=="speed"?hand_->getSpeedRangeRaw():hand_->getTorqueRangeRaw();
                c.ranges=std::vector<std::vector<double>>(size_,{double(range.first),double(range.second)});
            }
            controls_.push_back(c);
        }
        if(config.model=="L6" || config.model=="O6" || config.model=="L20_10")readable_.push_back("palm");
        if(config.model=="L20_10"){readable_.push_back("finger_force_sum");readable_.push_back("palm_force_sum");}
        if(config.model=="L25")operations_={"enable","disable"};
    }
    ~Legacy()override{try{close();}catch(...) {}}
    std::string meta()const override {
        return object({{"model",json(config_.model)},{"sdk",json("legacy")},{"simulated","false"},
            {"identity",json("legacy identity is not verified by the tool")},{"controls",controls_json(controls_)},
            {"readable",json(readable_)},{"operations",json(operations_)},
            {"validation",json("historical API profile; firmware-specific acceptance required")}});
    }
    std::string read(const std::string& name)override {
        if(std::find(readable_.begin(),readable_.end(),name)==readable_.end())throw std::invalid_argument("unsupported legacy reading");
        if(name=="version")return object({{"version",json(hand_->getVersion())}});
        if(name=="position")return raw_?reading(hand_->getPositionRaw()):reading(hand_->getPosition());
        if(name=="speed")return raw_?reading(hand_->getSpeedRaw()):reading(hand_->getSpeed());
        if(name=="torque")return raw_?reading(hand_->getTorqueRaw()):reading(hand_->getTorque());
        if(name=="temperature")return reading(hand_->getTemperature());
        if(name=="fault")return reading(hand_->getFaultCode());
        if(name=="finger_force_sum")return reading(hand_->getFingerForceSum());
        if(name=="palm_force_sum")return reading(hand_->getPalmForceSum());
        std::string matrices="[";
        if(name=="palm")matrices+=object({{"name",json("palm")},{"raw",json(hand_->getPalmForce())}});
        else {const auto fingers=hand_->getForce();for(size_t i=0;i<fingers.size();++i){if(i)matrices+=',';matrices+=object({{"name",json("finger_"+std::to_string(i))},{"raw",json(fingers[i])}});}}
        matrices+=']';return object({{"matrices",matrices},{"meta",object({{"origin",json("legacy_unspecified")},{"freshness",json("unknown")},{"unit",json("unverified raw count")}})}});
    }
    std::string write(const std::string& name,const std::vector<double>& values)override {
        const auto control=std::find_if(controls_.begin(),controls_.end(),[&](const auto& c){return c.name==name;});
        if(control==controls_.end())throw std::invalid_argument("unsupported legacy control");check_values(*control,values);
        for(double v:values)if(std::trunc(v)!=v)throw std::invalid_argument("legacy controls require integer values");
        if(raw_) {
            std::vector<int16_t> v;for(double x:values)v.push_back(static_cast<int16_t>(x));
            if(name=="position")hand_->setPositionRaw(v);else if(name=="speed")hand_->setSpeedRaw(v);else hand_->setTorqueRaw(v);
        }else{
            std::vector<uint8_t> v;for(double x:values)v.push_back(static_cast<uint8_t>(x));
            if(name=="position")hand_->setPosition(v);else if(name=="speed")hand_->setSpeed(v);else hand_->setTorque(v);
        }
        return object({{"stage",json("legacy_api_returned")},{"device_acknowledged","null"},{"mechanical_arrival_confirmed","false"}});
    }
    std::string operation(const std::string& name)override {
        if(std::find(operations_.begin(),operations_.end(),name)==operations_.end())throw std::invalid_argument("unsupported legacy operation");
        if(name=="enable")hand_->setEnable(std::vector<uint8_t>(5,0));else hand_->setDisable(std::vector<uint8_t>(5,1));
        return object({{"stage",json("legacy_api_returned")},{"mechanical_arrival_confirmed","false"}});
    }
    void close()override {
        hand_.reset();if(callbacks_)callbacks_->close();if(dispatcher_)dispatcher_->stop();if(modbus_)modbus_->close();
    }
};
std::unique_ptr<Backend>make_legacy(const Config& config){return std::make_unique<Legacy>(config);}
}
