// SPDX-License-Identifier: MIT
// Per-user CoreMIDI endpoints; the privileged native service remains the sole USB owner.
#import <Foundation/Foundation.h>
#import <CoreMIDI/CoreMIDI.h>
#import <xpc/xpc.h>
#include <mach/mach_time.h>
#include "mbox_midi_codec.h"
#define MBOX_MIDI_SERVICE "audio.necromancer.mbox2.transport"
#define MBOX_MIDI_SOURCE_ID 0x4d423249
#define MBOX_MIDI_DEST_ID 0x4d42324f
static MIDIClientRef gClient;
static MIDIEndpointRef gSource,gDestination;
static dispatch_queue_t gQueue;
static xpc_connection_t gConnection;
static dispatch_source_t gTimer;
static MboxMIDIParser gParser;
static uint64_t gGeneration,gInputEvents,gOutputPackets,gDropped,gReceivedErrors;
static unsigned gPending;
static bool gOnline,gSubscribed,gRequestPending;
static void bridgeLog(NSString *stage,NSDictionary *fields) {
    NSMutableDictionary *value=[fields mutableCopy]?:[NSMutableDictionary dictionary];value[@"stage"]=stage;
    value[@"utc"]=[[NSISO8601DateFormatter new] stringFromDate:NSDate.date];
    NSData *data=[NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingSortedKeys error:nil];
    fwrite(data.bytes,1,data.length,stdout);puts("");fflush(stdout);
}
static void setOnline(bool online) {
    if(gOnline==online)return;gOnline=online;
    MIDIObjectSetIntegerProperty(gSource,kMIDIPropertyOffline,!online);
    MIDIObjectSetIntegerProperty(gDestination,kMIDIPropertyOffline,!online);
    bridgeLog(@"midi.online",@{@"online":@(online),@"generation":@(gGeneration)});
}
static void receiveBytes(void *context,const uint8_t *bytes,size_t n,uint64_t timestamp) {
    (void)context;MIDIPacketList list;MIDIPacket *packet=MIDIPacketListInit(&list);
    if(!MIDIPacketListAdd(&list,sizeof(list),packet,timestamp,n,bytes) || MIDIReceived(gSource,&list)!=noErr)gReceivedErrors++;
    else gInputEvents++;
}
static void outputCallback(const MIDIPacketList *list,void *context,void *source) {
    (void)context;(void)source;const MIDIPacket *packet=&list->packet[0];
    for(UInt32 i=0;i<list->numPackets;i++,packet=MIDIPacketNext(packet)) {
        for(NSUInteger offset=0;offset<packet->length;) {
            NSUInteger n=MIN((NSUInteger)4096,packet->length-offset);
            if(__atomic_fetch_add(&gPending,1,__ATOMIC_RELAXED)>=128) {
                __atomic_fetch_sub(&gPending,1,__ATOMIC_RELAXED);__atomic_fetch_add(&gDropped,1,__ATOMIC_RELAXED);return;
            }
            NSData *data=[NSData dataWithBytes:packet->data+offset length:n];uint64_t stamp=packet->timeStamp;
            offset+=n;
            dispatch_async(gQueue,^{
                if(!gOnline || !gSubscribed || !gConnection) {
                    __atomic_fetch_sub(&gPending,1,__ATOMIC_RELAXED);__atomic_fetch_add(&gDropped,1,__ATOMIC_RELAXED);return;
                }
                xpc_object_t message=xpc_dictionary_create(NULL,NULL,0);
                xpc_dictionary_set_string(message,"operation","midi.send");
                xpc_dictionary_set_data(message,"data",data.bytes,data.length);
                xpc_dictionary_set_uint64(message,"timestamp",stamp);
                xpc_connection_send_message_with_reply(gConnection,message,gQueue,^(xpc_object_t reply){
                    __atomic_fetch_sub(&gPending,1,__ATOMIC_RELAXED);
                    if(xpc_get_type(reply)==XPC_TYPE_DICTIONARY && xpc_dictionary_get_bool(reply,"ok"))gOutputPackets++;
                    else __atomic_fetch_add(&gDropped,1,__ATOMIC_RELAXED);
                });
            });
        }
    }
}
static void connectService(void) {
    if(gConnection)return;
    xpc_connection_t connection=xpc_connection_create_mach_service(MBOX_MIDI_SERVICE,gQueue,XPC_CONNECTION_MACH_SERVICE_PRIVILEGED);
    gConnection=connection;
    xpc_connection_set_event_handler(connection,^(xpc_object_t event){
        if(connection!=gConnection)return;
        if(xpc_get_type(event)==XPC_TYPE_ERROR) {
            gSubscribed=false;gRequestPending=false;setOnline(false);memset(&gParser,0,sizeof(gParser));
            if(event==XPC_ERROR_CONNECTION_INVALID)gConnection=nil;
            return;
        }
        if(xpc_get_type(event)!=XPC_TYPE_DICTIONARY)return;
        const char *type=xpc_dictionary_get_string(event,"event");
        if(type && !strcmp(type,"midi.input")) {
            uint64_t generation=xpc_dictionary_get_uint64(event,"generation");
            if(gGeneration!=generation){gGeneration=generation;memset(&gParser,0,sizeof(gParser));}
            size_t n=0;const uint8_t *bytes=xpc_dictionary_get_data(event,"data",&n);
            if(bytes && n<=12)mbox_midi_feed(&gParser,bytes,n,xpc_dictionary_get_uint64(event,"timestamp"),receiveBytes,NULL);
            xpc_object_t reply=xpc_dictionary_create_reply(event);if(reply)xpc_connection_send_message(connection,reply);
        }
    });xpc_connection_resume(connection);
}
int main(void) {@autoreleasepool {
    gQueue=dispatch_queue_create("audio.necromancer.mbox.midibridge",dispatch_queue_attr_make_with_qos_class(DISPATCH_QUEUE_SERIAL,QOS_CLASS_USER_INITIATED,0));
    OSStatus status=MIDIClientCreate(CFSTR("Necromancer Mbox 2 MIDI"),NULL,NULL,&gClient);
    if(!status)status=MIDISourceCreate(gClient,CFSTR("Mbox 2 MIDI — Necromancer Audio"),&gSource);
    if(!status)status=MIDIDestinationCreate(gClient,CFSTR("Mbox 2 MIDI — Necromancer Audio"),outputCallback,NULL,&gDestination);
    if(!status)status=MIDIObjectSetIntegerProperty(gSource,kMIDIPropertyUniqueID,MBOX_MIDI_SOURCE_ID);
    if(!status)status=MIDIObjectSetIntegerProperty(gDestination,kMIDIPropertyUniqueID,MBOX_MIDI_DEST_ID);
    if(status){bridgeLog(@"midi.creation_failed",@{@"status":@(status)});if(gClient)MIDIClientDispose(gClient);return 1;}
    for(unsigned i=0;i<2;i++) {
        MIDIEndpointRef endpoint=i?gDestination:gSource;
        MIDIObjectSetStringProperty(endpoint,kMIDIPropertyManufacturer,CFSTR("Necromancer Audio"));
        MIDIObjectSetStringProperty(endpoint,kMIDIPropertyModel,CFSTR("Digidesign Mbox 2"));
        MIDIObjectSetIntegerProperty(endpoint,kMIDIPropertyOffline,1);
    }
    bridgeLog(@"midi.endpoints_created",@{@"source_uid":@(MBOX_MIDI_SOURCE_ID),@"destination_uid":@(MBOX_MIDI_DEST_ID)});
    gTimer=dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER,0,0,gQueue);
    dispatch_source_set_timer(gTimer,DISPATCH_TIME_NOW,NSEC_PER_SEC,50*NSEC_PER_MSEC);
    __block unsigned ticks=0;
    dispatch_source_set_event_handler(gTimer,^{
        connectService();if(gRequestPending)return;gRequestPending=true;
        xpc_connection_t connection=gConnection;
        xpc_object_t message=xpc_dictionary_create(NULL,NULL,0);
        xpc_dictionary_set_string(message,"operation",gSubscribed?"midi.status":"midi.subscribe");
        xpc_connection_send_message_with_reply(connection,message,gQueue,^(xpc_object_t reply){
            if(connection!=gConnection)return;gRequestPending=false;
            if(xpc_get_type(reply)!=XPC_TYPE_DICTIONARY){gSubscribed=false;setOnline(false);return;}
            gSubscribed=xpc_dictionary_get_bool(reply,"ok");
            uint64_t generation=xpc_dictionary_get_uint64(reply,"generation");
            if(gGeneration!=generation){gGeneration=generation;memset(&gParser,0,sizeof(gParser));}
            setOnline(gSubscribed && xpc_dictionary_get_uint64(reply,"online"));
            if(ticks++%10==0) {
                NSMutableDictionary *health=[@{@"online":@(gOnline),@"input_events":@(gInputEvents),
                    @"output_packets":@(gOutputPackets),@"dropped":@(__atomic_load_n(&gDropped,__ATOMIC_RELAXED)),
                    @"coremidi_errors":@(gReceivedErrors)} mutableCopy];
                for(NSString *key in @[@"input_bytes",@"output_wire_bytes",@"errors",@"pending_bytes",@"generation"])
                    health[key]=@(xpc_dictionary_get_uint64(reply,key.UTF8String));
                bridgeLog(@"midi.health",health);
            }
        });
    });dispatch_resume(gTimer);dispatch_main();
}}
