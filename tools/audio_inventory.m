// SPDX-License-Identifier: MIT
#import <Foundation/Foundation.h>
#import <CoreAudio/CoreAudio.h>

static NSDictionary *channels(AudioDeviceID dev, AudioObjectPropertyScope scope) {
    AudioObjectPropertyAddress a={kAudioDevicePropertyStreamConfiguration,scope,kAudioObjectPropertyElementMain};
    UInt32 size=0;
    OSStatus s=AudioObjectGetPropertyDataSize(dev,&a,0,NULL,&size);
    if(s || size<sizeof(UInt32)) return @{@"status":@(s),@"error":@"Stream configuration unavailable"};
    AudioBufferList *b=calloc(1,size);
    if(!b) return @{@"error":@"Allocation failed"};
    s=AudioObjectGetPropertyData(dev,&a,0,NULL,&size,b);
    UInt32 count=0;
    if(!s) for(UInt32 i=0;i<b->mNumberBuffers;i++) count+=b->mBuffers[i].mNumberChannels;
    free(b);
    return @{@"status":@(s),@"channels":@(count)};
}

int main(void) {
    @autoreleasepool {
        AudioObjectPropertyAddress a={kAudioHardwarePropertyDevices,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
        UInt32 size=0;
        OSStatus s=AudioObjectGetPropertyDataSize(kAudioObjectSystemObject,&a,0,NULL,&size);
        if(s) return 1;
        AudioDeviceID *ids=calloc(1,size);
        if(!ids) return 1;
        s=AudioObjectGetPropertyData(kAudioObjectSystemObject,&a,0,NULL,&size,ids);
        NSMutableArray *found=[NSMutableArray array];
        if(!s) for(UInt32 i=0;i<size/sizeof(*ids);i++) {
            CFStringRef name=NULL;
            UInt32 nsize=sizeof(name);
            AudioObjectPropertyAddress n={kAudioObjectPropertyName,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
            if(AudioObjectGetPropertyData(ids[i],&n,0,NULL,&nsize,&name) || !name) continue;
            NSString *str=CFBridgingRelease(name);
            if([str rangeOfString:@"Mbox" options:NSCaseInsensitiveSearch].location==NSNotFound) continue;
            NSMutableDictionary *d=[@{@"id":@(ids[i]),@"name":str,
                @"input":channels(ids[i],kAudioObjectPropertyScopeInput),
                @"output":channels(ids[i],kAudioObjectPropertyScopeOutput)} mutableCopy];
            UInt32 alive=0; nsize=sizeof(alive);
            n.mSelector=kAudioDevicePropertyDeviceIsAlive;
            OSStatus status=AudioObjectGetPropertyData(ids[i],&n,0,NULL,&nsize,&alive);
            d[@"alive"] = @{@"status":@(status),@"value":@(alive)};
            Float64 rate=0; nsize=sizeof(rate); n.mSelector=kAudioDevicePropertyNominalSampleRate;
            status=AudioObjectGetPropertyData(ids[i],&n,0,NULL,&nsize,&rate);
            d[@"nominal_sample_rate"] = @{@"status":@(status),@"value":@(rate)};
            [found addObject:d];
        }
        free(ids);
        NSData *json=[NSJSONSerialization dataWithJSONObject:@{@"status":@(s),@"mbox_devices":found}
            options:NSJSONWritingPrettyPrinted|NSJSONWritingSortedKeys error:nil];
        fwrite(json.bytes,1,json.length,stdout); fputc('\n',stdout);
        return s?1:0;
    }
}
