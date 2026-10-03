// SPDX-License-Identifier: MIT
// Interface 6 belongs to the same native capture owner as the working audio path.
#import <xpc/xpc.h>
#include <sys/stat.h>
#include <mach/mach_time.h>
#include "mbox_midi_codec.h"
static dispatch_queue_t gMIDIQueue;
static xpc_connection_t gMIDIPeer;
static NSUInteger gMIDIInFlight;

@interface MboxMIDITransport : NSObject {
    IOUSBHostInterface *_interface;
    IOUSBHostPipe *_input,*_output;
    NSMutableData *_readData,*_encoded;
    NSArray<NSMutableData *> *_writeBuffers;
    NSMutableArray<NSDictionary *> *_pending;
    dispatch_source_t _timer;
    MboxMIDIParser _parser;
    uint64_t _generation,_received,_sent,_errors,_dropped,_sequence;
    NSUInteger _pendingBytes,_offset;
    BOOL _stopping,_writing,_reading;
    double _nsPerTick;
}
- (BOOL)start:(io_service_t)device;
- (void)stop;
- (BOOL)send:(NSData *)data timestamp:(uint64_t)timestamp;
- (NSDictionary *)status;
- (void)append:(const uint8_t *)bytes length:(size_t)length;
- (void)failException:(NSException *)exception;
@end
static MboxMIDITransport *gMIDITransport;
static void midiEncodeEmit(void *context,const uint8_t *bytes,size_t n,uint64_t timestamp) {
    (void)timestamp;[(__bridge MboxMIDITransport *)context append:bytes length:n];
}
@implementation MboxMIDITransport
- (void)append:(const uint8_t *)bytes length:(size_t)n {
    uint8_t wire[4];if(mbox_midi_encode(wire,bytes,n))[_encoded appendBytes:wire length:4];
}
- (NSDictionary *)status {
    return @{@"online":@(!_stopping && _input && _output),@"generation":@(_generation),
        @"input_bytes":@(_received),@"output_wire_bytes":@(_sent),@"errors":@(_errors),
        @"dropped":@(_dropped),@"pending_bytes":@(_pendingBytes),@"pending_packets":@(_pending.count)};
}
- (void)failException:(NSException *)exception {
    _stopping=YES;_errors++;
    checkpoint(@"midi.exception",@{@"name":exception.name?:@"",@"reason":exception.reason?:@""});
}
- (void)read {
    if(_stopping)return;
    _reading=YES;NSError *error=nil;
    BOOL ok=[_input enqueueIORequestWithData:_readData completionTimeout:0 error:&error
        completionHandler:^(IOReturn status,NSUInteger transferred) {
            self->_reading=NO;if(self->_stopping)return;
            if(status!=kIOReturnSuccess || transferred>16) {
                self->_errors++;self->_stopping=YES;
                checkpoint(@"midi.input.error",@{@"status":@(status),@"bytes":@(transferred)});return;
            }
            uint8_t bytes[12];size_t n=0;
            if(!mbox_midi_decode(self->_readData.bytes,transferred,bytes,&n))self->_errors++;
            else if(n) {
                self->_received+=n;
                if(gMIDIPeer && gMIDIInFlight<128) {
                    xpc_connection_t peer=gMIDIPeer;
                    xpc_object_t event=xpc_dictionary_create(NULL,NULL,0);
                    xpc_dictionary_set_string(event,"event","midi.input");
                    xpc_dictionary_set_data(event,"data",bytes,n);
                    xpc_dictionary_set_uint64(event,"timestamp",mach_absolute_time());
                    xpc_dictionary_set_uint64(event,"generation",self->_generation);
                    gMIDIInFlight++;
                    xpc_connection_send_message_with_reply(peer,event,gMIDIQueue,^(xpc_object_t reply) {
                        (void)reply;if(peer==gMIDIPeer && gMIDIInFlight)gMIDIInFlight--;
                    });
                } else if(gMIDIPeer)self->_dropped+=n;
            }
            [self read];
        }];
    if(!ok) {_reading=NO;_errors++;_stopping=YES;checkpoint(@"midi.input.submit_failed",failure(error));}
}
- (void)drain {
    @try {[self drainChecked];} @catch(NSException *exception){[self failException:exception];}
}
- (void)drainChecked {
    if(_stopping || _writing)return;
    if(_offset>=_encoded.length) {
        [_encoded setLength:0];_offset=0;
        while(_pending.count && !_encoded.length) {
            NSDictionary *first=_pending[0];uint64_t due=[first[@"timestamp"] unsignedLongLongValue],now=mach_absolute_time();
            if(due>now) {
                uint64_t ns=(uint64_t)((due-now)*_nsPerTick);
                dispatch_source_set_timer(_timer,dispatch_time(DISPATCH_TIME_NOW,(int64_t)ns),DISPATCH_TIME_FOREVER,50000);return;
            }
            NSData *data=first[@"data"];_pendingBytes-=data.length;[_pending removeObjectAtIndex:0];
            mbox_midi_feed(&_parser,data.bytes,data.length,due,midiEncodeEmit,(__bridge void *)self);
        }
        if(!_encoded.length)return;
    }
    NSUInteger n=MIN((NSUInteger)16,_encoded.length-_offset);
    // IOUSBHost's ioData objects have immutable lengths. Preallocate every legal
    // packet size and retain that exact buffer until completion or synchronous abort.
    NSMutableData *writeData=_writeBuffers[n/4-1];
    memcpy(writeData.mutableBytes,(const uint8_t *)_encoded.bytes+_offset,n);
    _writing=YES;NSError *error=nil;
    BOOL ok=[_output enqueueIORequestWithData:writeData completionTimeout:2 error:&error
        completionHandler:^(IOReturn status,NSUInteger transferred) {
            self->_writing=NO;if(self->_stopping)return;
            if(status!=kIOReturnSuccess || transferred!=n) {
                self->_errors++;self->_stopping=YES;
                checkpoint(@"midi.output.error",@{@"status":@(status),@"bytes":@(transferred)});return;
            }
            self->_sent+=transferred;self->_offset+=transferred;[self drain];
        }];
    if(!ok) {_writing=NO;_errors++;_stopping=YES;checkpoint(@"midi.output.submit_failed",failure(error));}
}
- (BOOL)send:(NSData *)data timestamp:(uint64_t)timestamp {
    uint64_t now=mach_absolute_time();
    if(_stopping || !data.length || data.length>4096 || _pending.count>=1024 ||
       _pendingBytes+data.length>65536 || (timestamp>now && (timestamp-now)*_nsPerTick>30e9)) {_dropped+=data.length;return NO;}
    if(timestamp<now)timestamp=now;
    NSDictionary *item=@{@"data":data,@"timestamp":@(timestamp),@"sequence":@(_sequence++)};
    NSUInteger index=0;
    // Preserve arrival order at equal timestamps, including fragmented SysEx.
    while(index<_pending.count && [_pending[index][@"timestamp"] unsignedLongLongValue]<=timestamp)index++;
    [_pending insertObject:item atIndex:index];_pendingBytes+=data.length;[self drain];return YES;
}
- (BOOL)start:(io_service_t)device {
    NSError *error=nil;_generation=mach_absolute_time();
    mach_timebase_info_data_t tb;mach_timebase_info(&tb);_nsPerTick=(double)tb.numer/tb.denom;
    _pending=[NSMutableArray array];_encoded=[NSMutableData data];
    _interface=openInterface(device,6,gMIDIQueue,IOUSBHostObjectInitOptionsNone,&error);
    if(!_interface){checkpoint(@"midi.interface.failed",failure(error));return NO;}
    _input=[_interface copyPipeWithAddress:0x81 error:&error];
    _output=[_interface copyPipeWithAddress:0x02 error:&error];
    if(!_input || !_output){checkpoint(@"midi.pipes.failed",failure(error));return NO;}
    const IOUSBEndpointDescriptor *a=&_input.descriptors->descriptor,*b=&_output.descriptors->descriptor;
    if(a->bEndpointAddress!=0x81 || (a->bmAttributes&3)!=3 || OSSwapLittleToHostInt16(a->wMaxPacketSize)!=16 ||
       b->bEndpointAddress!=2 || (b->bmAttributes&3)!=2 || OSSwapLittleToHostInt16(b->wMaxPacketSize)!=16) {
        checkpoint(@"midi.profile.rejected",nil);return NO;
    }
    _readData=[_interface ioDataWithCapacity:16 error:&error];if(!_readData)return NO;
    NSMutableArray *buffers=[NSMutableArray array];
    for(NSUInteger length=4;length<=16;length+=4) {
        NSMutableData *buffer=[_interface ioDataWithCapacity:length error:&error];
        if(!buffer || buffer.length!=length)return NO;[buffers addObject:buffer];
    }
    _writeBuffers=buffers;
    _timer=dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER,0,0,gMIDIQueue);
    __weak MboxMIDITransport *weakSelf=self;
    dispatch_source_set_event_handler(_timer,^{[weakSelf drain];});dispatch_resume(_timer);
    dispatch_sync(gMIDIQueue,^{[self read];});
    checkpoint(@"midi.started",[self status]);return !_stopping;
}
- (void)stop {
    dispatch_sync(gMIDIQueue,^{self->_stopping=YES;if(self->_timer)dispatch_source_cancel(self->_timer);});
    // Never abort synchronously from the queue that services completions.
    [_input abortWithOption:IOUSBHostAbortOptionSynchronous error:nil];
    [_output abortWithOption:IOUSBHostAbortOptionSynchronous error:nil];
    dispatch_sync(gMIDIQueue,^{});[_interface destroy];
    checkpoint(@"midi.stopped",[self status]);
}
@end

static BOOL midiAuthorized(xpc_connection_t peer) {
    struct stat owner={0};uid_t uid=xpc_connection_get_euid(peer);
    return uid==0 || (stat("/dev/console",&owner)==0 && owner.st_uid>=500 && uid==owner.st_uid);
}
static void midiPeerDisconnected(xpc_connection_t peer) {
    dispatch_async(gMIDIQueue,^{if(peer==gMIDIPeer){gMIDIPeer=nil;gMIDIInFlight=0;}});
}
static void midiIPC(xpc_connection_t peer,xpc_object_t message) {
    dispatch_async(gMIDIQueue,^{
        xpc_object_t reply=xpc_dictionary_create_reply(message);if(!reply)return;
        const char *op=xpc_dictionary_get_string(message,"operation");BOOL ok=NO;
        if(midiAuthorized(peer)) {
            if(!strcmp(op,"midi.subscribe")) {
                if(!gMIDIPeer || gMIDIPeer==peer) {gMIDIPeer=peer;gMIDIInFlight=0;ok=YES;}
            } else if(!strcmp(op,"midi.send") && peer==gMIDIPeer && gMIDITransport) {
                size_t n=0;const void *bytes=xpc_dictionary_get_data(message,"data",&n);
                if(bytes && n>0 && n<=4096) {
                    @try {ok=[gMIDITransport send:[NSData dataWithBytes:bytes length:n]
                        timestamp:xpc_dictionary_get_uint64(message,"timestamp")];}
                    @catch(NSException *exception){[gMIDITransport failException:exception];}
                }
            } else if(!strcmp(op,"midi.status"))ok=YES;
        }
        xpc_dictionary_set_bool(reply,"ok",ok);
        NSDictionary *status=gMIDITransport?[gMIDITransport status]:@{@"online":@NO};
        for(NSString *key in status)xpc_dictionary_set_uint64(reply,key.UTF8String,[status[key] unsignedLongLongValue]);
        xpc_connection_send_message(peer,reply);
    });
}
