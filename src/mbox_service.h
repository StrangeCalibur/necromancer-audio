// SPDX-License-Identifier: MIT
#import <xpc/xpc.h>
#include <sys/mman.h>
#include <pwd.h>
#include <signal.h>
#include <mach/mach_time.h>
#include "mbox_shared.h"
static MboxShared *gShared;
static volatile sig_atomic_t gStop;
static xpc_connection_t gListener;
static dispatch_source_t gHealthTimer;
static void stopService(int signalNumber){(void)signalNumber;gStop=1;}
static BOOL startService(void){
    if(geteuid()!=0)return NO;
    gMIDIQueue=dispatch_queue_create("audio.necromancer.mbox.midi",dispatch_queue_attr_make_with_qos_class(DISPATCH_QUEUE_SERIAL,QOS_CLASS_USER_INITIATED,0));
    gShared=mmap(NULL,sizeof(*gShared),PROT_READ|PROT_WRITE,MAP_ANON|MAP_SHARED,-1,0);
    if(gShared==MAP_FAILED){gShared=NULL;return NO;}
    memset(gShared,0,sizeof(*gShared));gShared->magic=MBOX_SHARED_MAGIC;gShared->version=MBOX_SHARED_VERSION;
    struct passwd *audioUser=getpwnam("_coreaudiod");
    if(!audioUser)return NO;const uid_t audioUID=audioUser->pw_uid;
    xpc_object_t memory=xpc_shmem_create(gShared,sizeof(*gShared));
    if(!memory)return NO;
    gListener=xpc_connection_create_mach_service(MBOX_MACH_SERVICE,dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),XPC_CONNECTION_MACH_SERVICE_LISTENER);
    if(!gListener)return NO;
    xpc_connection_set_event_handler(gListener,^(xpc_object_t peer){
        if(xpc_get_type(peer)!=XPC_TYPE_CONNECTION)return;
        xpc_connection_set_event_handler(peer,^(xpc_object_t message){
            if(xpc_get_type(message)==XPC_TYPE_ERROR){midiPeerDisconnected(peer);return;}
            if(xpc_get_type(message)!=XPC_TYPE_DICTIONARY)return;
            const char *op=xpc_dictionary_get_string(message,"operation");
            if(op && strncmp(op,"midi.",5)==0){midiIPC(peer,message);return;}
            uid_t uid=xpc_connection_get_euid(peer);
            xpc_object_t reply=xpc_dictionary_create_reply(message);if(!reply)return;
            // Fixed operation; no paths, code, USB controls or arbitrary requests over IPC.
            if((uid==audioUID || uid==0) && op && strcmp(op,"connect")==0){
                xpc_dictionary_set_value(reply,"memory",memory);xpc_dictionary_set_uint64(reply,"version",MBOX_SHARED_VERSION);
            } else {xpc_dictionary_set_string(reply,"error","unauthorized or unsupported operation");}
            xpc_connection_send_message(peer,reply);
        });
        xpc_connection_resume(peer);
    });
    xpc_connection_resume(gListener);signal(SIGTERM,stopService);signal(SIGINT,stopService);
    gHealthTimer=dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER,0,0,dispatch_get_global_queue(QOS_CLASS_UTILITY,0));
    dispatch_source_set_timer(gHealthTimer,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC),5*NSEC_PER_SEC,NSEC_PER_MSEC*100);
    dispatch_source_set_event_handler(gHealthTimer,^{
        checkpoint(@"service.health",@{@"online":@(mbox_load(&gShared->online)),@"generation":@(mbox_load(&gShared->generation)),
            @"hardware_sample":@(mbox_load(&gShared->clock_sample)),@"output_written":@(mbox_load(&gShared->output_written)),
            @"output_consumed":@(mbox_load(&gShared->output_consumed)),@"output_missed":@(mbox_load(&gShared->output_missed)),
            @"input_written":@(mbox_load(&gShared->input_written)),@"clients":@(mbox_load(&gShared->clients)),
            @"clock_host":@(mbox_load(&gShared->clock_host)),@"now_host":@(mach_absolute_time()),
            @"output_valid":@(mbox_load(&gShared->output_valid)),@"output_nonzero":@(mbox_load(&gShared->output_nonzero)),
            @"hal_write_calls":@(mbox_load(&gShared->hal_write_calls)),@"hal_read_calls":@(mbox_load(&gShared->hal_read_calls)),
            @"hal_read_missed":@(mbox_load(&gShared->hal_read_missed)),@"hal_write_frame":@(mbox_load(&gShared->hal_write_frame)),
            @"hal_write_count":@(mbox_load(&gShared->hal_write_count)),@"zero_sample":@(mbox_load(&gShared->zero_sample)),
            @"zero_host":@(mbox_load(&gShared->zero_host)),@"zero_query":@(mbox_load(&gShared->zero_query)),
            @"playback_packets":@(mbox_load(&gShared->playback_packets)),@"capture_packets":@(mbox_load(&gShared->capture_packets)),
            @"feedback_valid":@(mbox_load(&gShared->feedback_valid)),@"iso_errors":@(mbox_load(&gShared->iso_errors))});
    });dispatch_resume(gHealthTimer);
    checkpoint(@"service.started",@{@"shared_bytes":@(sizeof(*gShared)),@"audio_uid":@(audioUID)});return YES;
}
