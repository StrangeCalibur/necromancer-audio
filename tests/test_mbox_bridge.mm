// SPDX-License-Identifier: MIT
// Exercise actual HAL handlers with synthetic shared memory; never opens USB.
#include "MboxDriver.mm"
#include <cassert>
#include <cstdio>
int main(){@autoreleasepool{
    auto *p=static_cast<MboxShared *>(mmap(nullptr,sizeof(MboxShared),PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0));assert(p!=MAP_FAILED);
    p->magic=MBOX_SHARED_MAGIC;p->version=MBOX_SHARED_VERSION;p->online=1;p->generation=71;p->heartbeat=mach_absolute_time();heartbeatLimit=UINT64_MAX;
    shared.publish(p,sizeof(MboxShared));Handler handler;assert(handler.OnStartIO()==noErr);assert(p->clients==1);
    const float out[]={0.25f,-0.75f,2.0f,-2.0f,NAN,INFINITY};
    handler.OnWriteMixedOutput({},0,1024,out,sizeof(out));
    float l,r;assert(mbox_ring_read(p->output,1024,&l,&r,71)&&l==0.25f&&r==-0.75f);
    assert(mbox_ring_read(p->output,1025,&l,&r,71)&&l==1&&r==-1);
    assert(mbox_ring_read(p->output,1026,&l,&r,71)&&l==0&&r==0);
    assert(!mbox_ring_read(p->output,1024,&l,&r,72));
    mbox_ring_write(p->input,5000,0.125f,-0.25f,71);float in[2]={};
    handler.OnReadClientInput({},{},0,5000,in,sizeof(in));assert(in[0]==0.125f&&in[1]==-0.25f);
    float second[2]={};handler.OnReadClientInput({},{},0,5000,second,sizeof(second));assert(memcmp(in,second,sizeof(in))==0);
    mbox_ring_write(p->input,5000+MBOX_RING_FRAMES,1,1,71);
    handler.OnReadClientInput({},{},0,5000,in,sizeof(in));assert(in[0]==0&&in[1]==0);
    auto context=std::make_shared<aspl::Context>(std::make_shared<aspl::Tracer>(aspl::Tracer::Mode::Noop));
    aspl::DeviceParameters params;params.SampleRate=48000;Device device(context,params);
    p->clock_sample=MBOX_RING_FRAMES;p->clock_host=mach_absolute_time();double sample;UInt64 host,seed;
    assert(device.GetZeroTimeStamp(device.GetID(),0,&sample,&host,&seed)==noErr && sample==MBOX_RING_FRAMES && seed==71 && host==p->clock_host);
    mach_timebase_info_data_t tb;mach_timebase_info(&tb);uint64_t period=(uint64_t)(1e9*tb.denom/(tb.numer*48000.)*MBOX_CLOCK_PERIOD);
    p->clock_sample=MBOX_RING_FRAMES-MBOX_CLOCK_PERIOD;p->clock_host=mach_absolute_time()-4*period-period/2;p->generation=72;
    assert(device.GetZeroTimeStamp(device.GetID(),0,&sample,&host,&seed)==noErr && sample==MBOX_RING_FRAMES && seed==72);
    UInt64 previousHost=host;p->clock_host-=period/10;
    assert(device.GetZeroTimeStamp(device.GetID(),0,&sample,&host,&seed)==noErr && sample==MBOX_RING_FRAMES && host==previousHost);
    p->clock_seq=1;assert(device.GetZeroTimeStamp(device.GetID(),0,&sample,&host,&seed)==kAudioHardwareNotRunningError);
    p->online=0;assert(handler.OnStartIO()==kAudioHardwareNotRunningError);
    in[0]=in[1]=1;handler.OnReadClientInput({},{},0,5000,in,sizeof(in));assert(in[0]==0&&in[1]==0);
    handler.OnStopIO();assert(p->clients==0);shared.publish(nullptr,0);
    puts("PASS: HAL stereo mapping, clipping, NaN handling, repeated input reads, ring wrap, generation isolation, hardware clock and offline behavior");
}}
