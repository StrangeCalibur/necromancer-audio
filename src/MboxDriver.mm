// SPDX-License-Identifier: MIT
// CoreAudio adapter using libASPL (MIT). USB and XPC never run in audio callbacks.
#include <aspl/Driver.hpp>
#import <Foundation/Foundation.h>
#include <xpc/xpc.h>
#include <mach/mach_time.h>
#include <atomic>
#include <cmath>
#include <sys/mman.h>
#include "mbox_shared.h"
#include "mbox_mapping.hpp"
namespace {
MboxMapping<MboxShared> shared([](MboxShared *p,size_t size){munmap(p,size);});
uint64_t heartbeatLimit;
xpc_connection_t connection;
dispatch_queue_t worker;
dispatch_source_t timer;
bool connecting=false;
std::weak_ptr<aspl::Device> deviceRef;

bool Live(MboxShared *p){
    if(!p || mbox_load(&p->magic)!=MBOX_SHARED_MAGIC || mbox_load(&p->version)!=MBOX_SHARED_VERSION || !mbox_load(&p->online))return false;
    const uint64_t h=mbox_load(&p->heartbeat),now=mach_absolute_time();
    return h && now>=h && now-h<heartbeatLimit;
}
void Connect(){
    if(connecting || shared.get() || !shared.canPublish())return;
    connecting=true;
    if(connection)xpc_connection_cancel(connection);
    connection=xpc_connection_create_mach_service(MBOX_MACH_SERVICE,worker,XPC_CONNECTION_MACH_SERVICE_PRIVILEGED);
    if(!connection){connecting=false;return;}
    xpc_connection_t current=connection;
    xpc_connection_set_event_handler(current,^(xpc_object_t event){
        if(connection==current && xpc_get_type(event)==XPC_TYPE_ERROR){shared.publish(nullptr,0);connecting=false;}
    });
    xpc_connection_resume(current);
    xpc_object_t request=xpc_dictionary_create(NULL,NULL,0);xpc_dictionary_set_string(request,"operation","connect");
    xpc_connection_send_message_with_reply(current,request,worker,^(xpc_object_t reply){
        if(connection!=current)return;
        connecting=false;
        if(xpc_get_type(reply)!=XPC_TYPE_DICTIONARY)return;
        xpc_object_t memory=xpc_dictionary_get_value(reply,"memory");if(!memory || xpc_get_type(memory)!=XPC_TYPE_SHMEM)return;
        void *address=nullptr;size_t size=xpc_shmem_map(memory,&address);
        if(size<sizeof(MboxShared) || size>sizeof(MboxShared)+16384 || !address){if(address && size)munmap(address,size);return;}
        auto *p=static_cast<MboxShared *>(address);
        if(mbox_load(&p->magic)!=MBOX_SHARED_MAGIC || mbox_load(&p->version)!=MBOX_SHARED_VERSION){munmap(address,size);return;}
        shared.publish(p,size);
    });
}
class Handler final:public aspl::ControlRequestHandler,public aspl::IORequestHandler {
public:
    OSStatus OnStartIO() override {
        auto reader=shared.read();auto *p=reader.get();if(!Live(p))return kAudioHardwareNotRunningError;
        mbox_store(&p->clients,1);return noErr;
    }
    void OnStopIO() override {auto reader=shared.read();auto *p=reader.get();if(p)mbox_store(&p->clients,0);}
    void OnWriteMixedOutput(const std::shared_ptr<aspl::Stream>&,Float64,Float64 timestamp,const void *bytes,UInt32 count) override {
        auto reader=shared.read();auto *p=reader.get();
        if(!Live(p) || !std::isfinite(timestamp) || timestamp<0 || timestamp>9e15 || count%8 || count/8>MBOX_RING_FRAMES)return;
        uint64_t frame=static_cast<uint64_t>(std::llround(timestamp)),generation=mbox_load(&p->generation);
        __atomic_fetch_add(&p->hal_write_calls,1,__ATOMIC_RELAXED);
        mbox_store(&p->hal_write_frame,frame);mbox_store(&p->hal_write_count,count/8);
        const float *samples=static_cast<const float *>(bytes);
        for(uint32_t i=0;i<count/8;i++)mbox_ring_write(p->output,frame+i,samples[2*i],samples[2*i+1],generation);
        __atomic_fetch_add(&p->output_written,count/8,__ATOMIC_RELAXED);
    }
    void OnReadClientInput(const std::shared_ptr<aspl::Client>&,const std::shared_ptr<aspl::Stream>&,
        Float64,Float64 timestamp,void *bytes,UInt32 count) override {
        memset(bytes,0,count);auto reader=shared.read();auto *p=reader.get();
        if(!Live(p) || !std::isfinite(timestamp) || timestamp<0 || timestamp>9e15 || count%8 || count/8>MBOX_RING_FRAMES)return;
        uint64_t frame=static_cast<uint64_t>(std::llround(timestamp)),generation=mbox_load(&p->generation);
        __atomic_fetch_add(&p->hal_read_calls,1,__ATOMIC_RELAXED);
        float *samples=static_cast<float *>(bytes);
        for(uint32_t i=0;i<count/8;i++)if(!mbox_ring_read(p->input,frame+i,&samples[2*i],&samples[2*i+1],generation))
            __atomic_fetch_add(&p->hal_read_missed,1,__ATOMIC_RELAXED);
    }
};
class Device final:public aspl::Device {
    uint64_t lastSample_=0,lastHost_=0,lastSeed_=0;
    double ticksPerFrame_;
public:
    Device(std::shared_ptr<const aspl::Context> context,const aspl::DeviceParameters& params):aspl::Device(context,params){
        mach_timebase_info_data_t tb;mach_timebase_info(&tb);ticksPerFrame_=1e9*tb.denom/(tb.numer*48000.);
    }
    UInt32 GetTransportType() const override {return kAudioDeviceTransportTypeUSB;}
protected:
    OSStatus GetZeroTimeStampImpl(UInt32,Float64 *sample,UInt64 *host,UInt64 *seed) override {
        auto reader=shared.read();auto *p=reader.get();if(!Live(p))return kAudioHardwareNotRunningError;
        // USB completions arrive in batches. Extrapolate the most recent elapsed
        // hardware boundary, then report only full ring wraps. AudioServerPlugIn.h
        // requires ZeroTimeStampPeriod >= 10923 frames; a USB-sized period causes
        // repeated TimeStampOutOfLine resets. Keep reported wrap times immutable.
        for(unsigned i=0;i<4;i++){
            uint64_t seq=mbox_load(&p->clock_seq);if(seq&1)continue;
            uint64_t s=mbox_load(&p->clock_sample),h=mbox_load(&p->clock_host),g=mbox_load(&p->generation);
            if(seq==mbox_load(&p->clock_seq)){
                const uint64_t now=mach_absolute_time();
                if(now>h){
                    uint64_t periods=static_cast<uint64_t>((now-h)/(ticksPerFrame_*MBOX_CLOCK_PERIOD));
                    if(periods>96)return kAudioHardwareNotRunningError;
                    s+=periods*MBOX_CLOCK_PERIOD;h+=static_cast<uint64_t>(periods*MBOX_CLOCK_PERIOD*ticksPerFrame_);
                }
                uint64_t remainder=s%MBOX_RING_FRAMES;
                s-=remainder;h-=static_cast<uint64_t>(remainder*ticksPerFrame_);
                if(g==lastSeed_ && s<=lastSample_){s=lastSample_;h=lastHost_;}
                lastSample_=s;lastHost_=h;lastSeed_=g;
                *sample=static_cast<double>(s);*host=h;*seed=g;
                mbox_store(&p->zero_sample,s);mbox_store(&p->zero_host,h);mbox_store(&p->zero_query,now);
                return noErr;
            }
        }
        return kAudioHardwareNotRunningError;
    }
    OSStatus SetNominalSampleRateImpl(Float64 rate) override {
        return rate==48000?aspl::Device::SetNominalSampleRateImpl(rate):kAudioDeviceUnsupportedFormatError;
    }
};
std::shared_ptr<aspl::Driver> Create(){
    mach_timebase_info_data_t tb;mach_timebase_info(&tb);heartbeatLimit=static_cast<uint64_t>(1e9*tb.denom/tb.numer);
    auto context=std::make_shared<aspl::Context>(std::make_shared<aspl::Tracer>(aspl::Tracer::Mode::Syslog));
    aspl::DeviceParameters p;p.Name="Mbox 2 — Necromancer Audio";p.Manufacturer="Necromancer Audio";
    p.DeviceUID="audio.necromancer.mbox2.0dba.3000";p.ModelUID="audio.necromancer.mbox2";p.FirmwareVersion="1.43";
    p.SampleRate=48000;p.ChannelCount=2;p.EnableMixing=true;p.Latency=48;p.SafetyOffset=4096;p.ZeroTimeStampPeriod=MBOX_RING_FRAMES;
    p.ClockIsStable=false;p.CanBeDefaultForSystemSounds=false;
    auto device=std::make_shared<Device>(context,p);device->SetIsAlive(false);
    for(aspl::Direction direction:{aspl::Direction::Output,aspl::Direction::Input}){
        aspl::StreamParameters s;s.Direction=direction;
        s.Format={48000,kAudioFormatLinearPCM,kAudioFormatFlagIsFloat|kAudioFormatFlagsNativeEndian|kAudioFormatFlagIsPacked,8,1,8,2,32,0};
        device->AddStreamAsync(s);
    }
    auto handler=std::make_shared<Handler>();device->SetControlHandler(handler);device->SetIOHandler(handler);
    auto plugin=std::make_shared<aspl::Plugin>(context);plugin->AddDevice(device);deviceRef=device;
    worker=dispatch_queue_create("audio.necromancer.mbox2.hal-control",DISPATCH_QUEUE_SERIAL);
    timer=dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER,0,0,worker);
    dispatch_source_set_timer(timer,DISPATCH_TIME_NOW,NSEC_PER_SEC/2,NSEC_PER_MSEC*50);
    dispatch_source_set_event_handler(timer,^{
        shared.collect();Connect();auto d=deviceRef.lock();bool alive=Live(shared.get());
        if(d && d->GetIsAlive()!=alive)d->SetIsAlive(alive);
    });dispatch_resume(timer);
    return std::make_shared<aspl::Driver>(context,plugin);
}
}
extern "C" void *MboxDriverEntryPoint(CFAllocatorRef,CFUUIDRef type){
    if(!CFEqual(type,kAudioServerPlugInTypeUUID))return nullptr;
    static auto driver=Create();return driver->GetReference();
}
