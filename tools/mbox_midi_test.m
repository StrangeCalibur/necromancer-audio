// SPDX-License-Identifier: MIT
// Bounded physical loopback test. Exact selected CoreMIDI endpoints only; no MIDI thru.
#import <Foundation/Foundation.h>
#import <CoreMIDI/CoreMIDI.h>
#include <mach/mach_time.h>
#include <pthread.h>
#include <unistd.h>
#include "mbox_midi_codec.h"
static MIDIEndpointRef softwareSource;
static MboxMIDIParser softwareOutputParser,softwareInputParser;
static void softwareInput(void *context,const uint8_t *bytes,size_t n,uint64_t stamp) {
    (void)context;MIDIPacketList list;MIDIPacket *p=MIDIPacketListInit(&list);
    MIDIPacketListAdd(&list,sizeof(list),p,stamp,n,bytes);MIDIReceived(softwareSource,&list);
}
static void softwareWire(void *context,const uint8_t *bytes,size_t n,uint64_t stamp) {
    (void)context;uint8_t wire[4],decoded[12];size_t count;
    if(mbox_midi_encode(wire,bytes,n) && mbox_midi_decode(wire,4,decoded,&count))
        mbox_midi_feed(&softwareInputParser,decoded,count,stamp,softwareInput,NULL);
}
static void softwareOutput(const MIDIPacketList *list,void *context,void *connection) {
    (void)context;(void)connection;const MIDIPacket *p=&list->packet[0];
    for(UInt32 i=0;i<list->numPackets;i++,p=MIDIPacketNext(p))
        mbox_midi_feed(&softwareOutputParser,p->data,p->length,p->timeStamp,softwareWire,NULL);
}
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static uint8_t received[16384];static size_t receivedCount;static bool overflow;
static uint64_t firstTimestamp,lastTimestamp;static unsigned callbacks;
static void input(const MIDIPacketList *list,void *ref,void *connection) {
    (void)ref;(void)connection;pthread_mutex_lock(&lock);
    const MIDIPacket *p=&list->packet[0];callbacks++;
    for(UInt32 i=0;i<list->numPackets;i++,p=MIDIPacketNext(p)) {
        if(p->length>sizeof(received)-receivedCount){overflow=true;continue;}
        memcpy(received+receivedCount,p->data,p->length);receivedCount+=p->length;
        if(!firstTimestamp)firstTimestamp=p->timeStamp;lastTimestamp=p->timeStamp;
    }pthread_mutex_unlock(&lock);
}
static NSString *hex(const uint8_t *bytes,size_t n) {
    NSMutableString *result=[NSMutableString string];for(size_t i=0;i<n;i++)[result appendFormat:@"%02x",bytes[i]];return result;
}
int main(int argc,const char **argv) {@autoreleasepool {
    bool software=argc==2 && !strcmp(argv[1],"--software");
    bool outputOnly=argc==3 && !strcmp(argv[1],"--output-only");
    if(!software && !outputOnly && (argc!=4 || strcmp(argv[1],"--loop"))){fprintf(stderr,"Usage: mbox_midi_test --loop source_uid destination_uid | --software | --output-only destination_uid\nConnect destination DIN OUT to source DIN IN first. Sends note-off, controller, timing and test SysEx data.\n");return 2;}
    SInt32 sourceUID=software?0x4d425449:outputOnly?0x4d423249:(SInt32)strtol(argv[2],NULL,10);
    SInt32 destUID=software?0x4d42544f:(SInt32)strtol(argv[outputOnly?2:3],NULL,10);
    MIDIClientRef client=0;MIDIPortRef inPort=0,outPort=0;MIDIObjectRef source=0,dest=0;MIDIObjectType type;
    OSStatus status=MIDIClientCreate(CFSTR("Necromancer physical MIDI test"),NULL,NULL,&client);
    if(software && !status) {
        MIDIEndpointRef destination;
        status=MIDISourceCreate(client,CFSTR("Necromancer temporary software test input"),&softwareSource);
        if(!status)status=MIDIDestinationCreate(client,CFSTR("Necromancer temporary software test output"),softwareOutput,NULL,&destination);
        if(!status)status=MIDIObjectSetIntegerProperty(softwareSource,kMIDIPropertyUniqueID,sourceUID);
        if(!status)status=MIDIObjectSetIntegerProperty(destination,kMIDIPropertyUniqueID,destUID);
    }
    if(!status)status=MIDIObjectFindByUniqueID(sourceUID,&source,&type);
    if(status || type!=kMIDIObjectType_Source){fprintf(stderr,"Exact source unavailable\n");return 1;}
    status=MIDIObjectFindByUniqueID(destUID,&dest,&type);
    if(status || type!=kMIDIObjectType_Destination){fprintf(stderr,"Exact destination unavailable\n");return 1;}
    SInt32 offline=0;MIDIObjectGetIntegerProperty(source,kMIDIPropertyOffline,&offline);
    if(offline){fprintf(stderr,"Source offline\n");return 1;}
    MIDIObjectGetIntegerProperty(dest,kMIDIPropertyOffline,&offline);
    if(offline){fprintf(stderr,"Destination offline\n");return 1;}
    status=MIDIInputPortCreate(client,CFSTR("Loopback receive"),input,NULL,&inPort);
    if(!status)status=MIDIOutputPortCreate(client,CFSTR("Loopback send"),&outPort);
    if(!status)status=MIDIPortConnectSource(inPort,source,NULL);
    if(status){fprintf(stderr,"MIDI setup failed: %d\n",(int)status);MIDIClientDispose(client);return 1;}
    usleep(100000);
    NSMutableArray<NSData *> *messages=[NSMutableArray array];
    const uint8_t one[]={0xf8},two[]={0xcf,7},three[]={0x8f,60,0},common[]={0xf2,1,2};
    [messages addObject:[NSData dataWithBytes:one length:sizeof(one)]];
    [messages addObject:[NSData dataWithBytes:two length:sizeof(two)]];
    [messages addObject:[NSData dataWithBytes:three length:sizeof(three)]];
    [messages addObject:[NSData dataWithBytes:common length:sizeof(common)]];
    for(size_t size=2;size<=8;size++) {
        uint8_t sysex[12]={0xf0,0x7d};for(size_t i=2;i<size+2;i++)sysex[i]=(uint8_t)(i+size);
        sysex[size+2]=0xf7;[messages addObject:[NSData dataWithBytes:sysex length:size+3]];
    }
    uint8_t large[259]={0xf0,0x7d};for(size_t i=2;i<258;i++)large[i]=(uint8_t)(i%128);large[258]=0xf7;
    [messages addObject:[NSData dataWithBytes:large length:sizeof(large)]];
    for(uint8_t i=0;i<64;i++) {uint8_t bytes[]={0x8f,i,0};[messages addObject:[NSData dataWithBytes:bytes length:3]];}
    NSMutableData *expected=[NSMutableData data];
    mach_timebase_info_data_t tb;mach_timebase_info(&tb);double ticksPerNs=(double)tb.denom/tb.numer;
    uint64_t started=mach_absolute_time();
    for(NSUInteger i=0;i<messages.count;i++) {
        NSData *data=messages[i];[expected appendData:data];
        // Enough spacing for DIN serialization, including the 259-byte SysEx.
        uint64_t when=started+(uint64_t)((200e6+i*100e6)*ticksPerNs);
        union {MIDIPacketList list;uint8_t space[1024];} buffer;
        MIDIPacket *packet=MIDIPacketListInit(&buffer.list);
        if(!MIDIPacketListAdd(&buffer.list,sizeof(buffer),packet,when,data.length,data.bytes)){status=-1;break;}
        status=MIDISend(outPort,dest,&buffer.list);if(status)break;
    }
    NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:10];
    while(deadline.timeIntervalSinceNow>0) {
        CFRunLoopRunInMode(kCFRunLoopDefaultMode,.02,false);
        pthread_mutex_lock(&lock);bool done=receivedCount>=expected.length || overflow;pthread_mutex_unlock(&lock);
        if(done)break;
    }
    usleep(150000);MIDIPortDisconnectSource(inPort,source);MIDIClientDispose(client);
    pthread_mutex_lock(&lock);
    bool match=!status && !overflow && receivedCount==expected.length && !memcmp(received,expected.bytes,expected.length);
    double delay=firstTimestamp?(firstTimestamp-started)/ticksPerNs/1e6:0;
    NSDictionary *result=@{@"pass":@(outputOnly?!status:match),@"physical_loopback_verified":@(!software && !outputOnly && match),
        @"output_only":@(outputOnly),@"software_only":@(software),@"source_uid":@(sourceUID),@"destination_uid":@(destUID),
        @"expected_bytes":@(expected.length),@"received_bytes":@(receivedCount),@"messages_sent":@(messages.count),
        @"callbacks":@(callbacks),@"overflow":@(overflow),@"send_status":@(status),
        @"first_timestamp_delay_ms":@(delay),@"first_timestamp":@(firstTimestamp),@"last_timestamp":@(lastTimestamp),
        @"expected_hex":hex(expected.bytes,expected.length),@"received_hex":hex(received,receivedCount),
        @"utc":[[NSISO8601DateFormatter new] stringFromDate:NSDate.date]};
    NSData *json=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];
    pthread_mutex_unlock(&lock);fwrite(json.bytes,1,json.length,stdout);puts("");return (outputOnly?!status:match)?0:1;
}}
