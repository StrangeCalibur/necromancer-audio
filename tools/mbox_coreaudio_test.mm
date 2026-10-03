// SPDX-License-Identifier: MIT
// Bounded client proof through the published CoreAudio device, no direct USB access.
#import <Foundation/Foundation.h>
#import <CoreAudio/CoreAudio.h>
#include <atomic>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>
#include <fcntl.h>
struct State {std::atomic<uint64_t> outputFrames{0},inputFrames{0},calls{0},badLayouts{0};float *record=nullptr;size_t capacity=48000*10;bool tone=false;double firstInputTime=0,firstOutputTime=0;uint64_t firstHostTime=0,lastHostTime=0;double lastOutputTime=0,nextOutputTime=0,nextInputTime=0;uint32_t firstOutBytes=0;uint64_t discontinuities=0,inputDiscontinuities=0,toneFrames=0;};
static OSStatus io(AudioDeviceID,const AudioTimeStamp *now,const AudioBufferList *in,const AudioTimeStamp *inputTime,AudioBufferList *out,const AudioTimeStamp *outputTime,void *ctx){
    auto *s=static_cast<State*>(ctx);if(s->calls.fetch_add(1,std::memory_order_relaxed)==0){s->firstInputTime=inputTime->mSampleTime;s->firstOutputTime=outputTime->mSampleTime;s->firstHostTime=now->mHostTime;if(out&&out->mNumberBuffers)s->firstOutBytes=out->mBuffers[0].mDataByteSize;}
    s->lastHostTime=now->mHostTime;s->lastOutputTime=outputTime->mSampleTime;
    if(out && out->mNumberBuffers==1 && out->mBuffers[0].mNumberChannels==2 && out->mBuffers[0].mDataByteSize%8==0){
        uint32_t frames=out->mBuffers[0].mDataByteSize/8;float *p=static_cast<float *>(out->mBuffers[0].mData);
        if(s->nextOutputTime && fabs(outputTime->mSampleTime-s->nextOutputTime)>0.5)s->discontinuities++;
        s->nextOutputTime=outputTime->mSampleTime+frames;
        int64_t start=llround(outputTime->mSampleTime-s->firstOutputTime);
        for(uint32_t i=0;i<frames;i++){
            int64_t position=(int64_t)(start+i)-2*48000;float v=0;
            if(s->tone && position>=0 && position<2*48000){
                double env=fmin(1,fmin(position/4800.,(2*48000-1-position)/4800.));
                v=(float)(0.007943282347242816*env*sin(6.283185307179586*(position%100)/100.));
                s->toneFrames++;
            }
            p[i*2]=p[i*2+1]=v;
        }s->outputFrames.fetch_add(frames,std::memory_order_relaxed);
    }else if(out){
        s->badLayouts.fetch_add(1,std::memory_order_relaxed);
        for(UInt32 i=0;i<out->mNumberBuffers;i++)if(out->mBuffers[i].mData)memset(out->mBuffers[i].mData,0,out->mBuffers[i].mDataByteSize);
    }
    if(in && in->mNumberBuffers==1 && in->mBuffers[0].mNumberChannels==2 && in->mBuffers[0].mDataByteSize%8==0){
        uint32_t frames=in->mBuffers[0].mDataByteSize/8;uint64_t start=s->inputFrames.load(std::memory_order_relaxed);
        if(s->nextInputTime && fabs(inputTime->mSampleTime-s->nextInputTime)>0.5)s->inputDiscontinuities++;
        s->nextInputTime=inputTime->mSampleTime+frames;
        if(start+frames<=s->capacity)memcpy(s->record+start*2,in->mBuffers[0].mData,frames*8);
        s->inputFrames.fetch_add(frames,std::memory_order_relaxed);
    }else if(in)s->badLayouts.fetch_add(1,std::memory_order_relaxed);
    return noErr;
}
static void put16(FILE *f,uint16_t n){fputc(n&255,f);fputc(n>>8,f);}
static void put32(FILE *f,uint32_t n){put16(f,n&65535);put16(f,n>>16);}
static bool saveWave(FILE *f,const float *samples,size_t frames){
    const uint32_t bytes=(uint32_t)(frames*6);
    fwrite("RIFF",1,4,f);put32(f,36+bytes);fwrite("WAVEfmt ",1,8,f);put32(f,16);
    put16(f,1);put16(f,2);put32(f,48000);put32(f,48000*6);put16(f,6);put16(f,24);
    fwrite("data",1,4,f);put32(f,bytes);
    for(size_t i=0;i<frames*2;i++){
        double sample=std::isfinite(samples[i])?samples[i]:0;
        int32_t value=(int32_t)llround(std::max(-8388608.,std::min(8388607.,sample*8388608.)));
        fputc(value&255,f);fputc((value>>8)&255,f);fputc((value>>16)&255,f);
    }
    const bool ok=!ferror(f);return fclose(f)==0 && ok;
}
int main(int argc,char **argv){@autoreleasepool{
    const bool recording=argc>1 && !strcmp(argv[1],"--record");const int durationArg=recording?3:2;
    if((argc!=durationArg && argc!=durationArg+1) || (!recording && strcmp(argv[1],"--silence") && strcmp(argv[1],"--tone"))){fprintf(stderr,"Usage: mbox_coreaudio_test --silence | --tone [seconds: 8..60]\n       mbox_coreaudio_test --record new-output.wav [seconds: 8..60]\nUses the Necromancer Mbox2 only. Recording sends silence and never monitors its input.\n");return 2;}
    char *end=nullptr;long seconds=argc==durationArg+1?strtol(argv[durationArg],&end,10):8;
    if(seconds<8 || seconds>60 || (end && *end))return 2;
    State state;state.tone=!strcmp(argv[1],"--tone");state.capacity=(seconds+1)*48000;
    state.record=static_cast<float *>(calloc(state.capacity*2,sizeof(float)));
    if(!state.record)return 1;
    FILE *wave=nullptr;
    if(recording){
        int fd=open(argv[2],O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW,0600);
        if(fd<0){perror("Create recording");free(state.record);return 1;}
        wave=fdopen(fd,"wb");if(!wave){close(fd);free(state.record);return 1;}
    }
    CFStringRef uid=CFSTR("audio.necromancer.mbox2.0dba.3000");AudioDeviceID device=kAudioObjectUnknown;
    AudioValueTranslation translate={&uid,sizeof(uid),&device,sizeof(device)};UInt32 size=sizeof(translate);
    AudioObjectPropertyAddress address={kAudioHardwarePropertyDeviceForUID,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
    OSStatus status=AudioObjectGetPropertyData(kAudioObjectSystemObject,&address,0,NULL,&size,&translate);
    if(status || !device){fprintf(stderr,"CoreAudio Mbox2 device unavailable (%d)\n",(int)status);if(wave)fclose(wave);free(state.record);return 1;}
    AudioDeviceIOProcID proc=nullptr;status=AudioDeviceCreateIOProcID(device,io,&state,&proc);
    if(!status)status=AudioDeviceStart(device,proc);
    if(!status){fprintf(stderr,"CoreAudio %s test running for %ld seconds\n",recording?"recording":state.tone?"quiet tone":"silence",seconds);sleep((unsigned)seconds);AudioDeviceStop(device,proc);}
    if(proc)AudioDeviceDestroyIOProcID(device,proc);
    double energy=0,peak=0,channelEnergy[2]={},channelPeak[2]={};size_t samples=std::min((size_t)state.inputFrames.load(),state.capacity)*2;size_t nonzero=0,invalid=0,clipped[2]={};
    for(size_t i=0;i<samples;i++){double v=state.record[i];if(!std::isfinite(v)){invalid++;continue;}energy+=v*v;peak=fmax(peak,fabs(v));if(v)nonzero++;channelEnergy[i%2]+=v*v;channelPeak[i%2]=fmax(channelPeak[i%2],fabs(v));if(fabs(v)>=.999)clipped[i%2]++;}
    bool saved=wave?saveWave(wave,state.record,samples/2):true;
    free(state.record);
    NSMutableArray *channels=[NSMutableArray array];
    for(int c=0;c<2;c++)[channels addObject:@{@"input":@(c+1),@"peak_dbfs":@(channelPeak[c]?20*log10(channelPeak[c]):-144),@"rms_dbfs":@(channelEnergy[c]&&samples?10*log10(channelEnergy[c]/(samples/2)):-144),@"clipped_samples":@(clipped[c])}];
    NSDictionary *result=@{@"status":@(status),@"device_id":@(device),@"tone":@(state.tone),@"tone_frames":@(state.toneFrames),@"discontinuities":@(state.discontinuities),@"input_discontinuities":@(state.inputDiscontinuities),@"channels":channels,@"recording_file":recording?[NSString stringWithUTF8String:argv[2]]:@"",@"recording_saved":@(recording&&saved),@"first_input_time":@(state.firstInputTime),@"first_output_time":@(state.firstOutputTime),@"first_host_time":@(state.firstHostTime),@"last_host_time":@(state.lastHostTime),@"last_output_time":@(state.lastOutputTime),@"first_output_bytes":@(state.firstOutBytes),@"callbacks":@(state.calls.load()),@"output_frames":@(state.outputFrames.load()),@"input_frames":@(state.inputFrames.load()),@"bad_layouts":@(state.badLayouts.load()),@"nonzero_input_samples":@(nonzero),@"invalid_input_samples":@(invalid),@"input_peak_dbfs":@(peak?20*log10(peak):-144),@"input_rms_dbfs":@(energy&&samples?10*log10(energy/samples):-144)};
    NSData *data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted|NSJSONWritingSortedKeys error:nil];fwrite(data.bytes,1,data.length,stdout);fputc('\n',stdout);
    return status || !saved || state.outputFrames<(uint64_t)(seconds*48000-24000) || state.inputFrames<(uint64_t)(seconds*48000-24000) || state.badLayouts || invalid || state.discontinuities || state.inputDiscontinuities || (state.tone && state.toneFrames!=96000)?1:0;
}}
