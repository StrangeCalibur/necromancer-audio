// SPDX-License-Identifier: MIT
// Exercise the real transport against the immutable-buffer/asynchronous-completion contract.
#define main mboxNativeProgramMain
#include "mbox_native.m"
#undef main
#include <assert.h>
@interface FixedMIDIData : NSMutableData {NSMutableData *_storage;}
- (instancetype)initWithSize:(NSUInteger)size;
@end
@implementation FixedMIDIData
- (instancetype)initWithSize:(NSUInteger)size {if((self=[super init]))_storage=[NSMutableData dataWithLength:size];return self;}
- (NSUInteger)length{return _storage.length;}
- (const void *)bytes{return _storage.bytes;}
- (void *)mutableBytes{return _storage.mutableBytes;}
- (void)setLength:(NSUInteger)length {(void)length;[NSException raise:@"Immutable USB length" format:@"ioData length cannot change"];}
@end
@interface FakeMIDIPipe : NSObject
@property NSMutableData *received;
@property BOOL reject;
@property dispatch_semaphore_t completed;
@end
@implementation FakeMIDIPipe
- (BOOL)enqueueIORequestWithData:(NSMutableData *)data completionTimeout:(NSTimeInterval)timeout
                           error:(NSError **)error completionHandler:(IOUSBHostCompletionHandler)completion {
    (void)timeout;(void)error;if(_reject)return NO;
    assert(data.length>=4 && data.length<=16 && data.length%4==0);
    // Read the retained buffer only on a later turn, just like asynchronous USB.
    dispatch_async(gMIDIQueue,^{[self.received appendData:data];completion(kIOReturnSuccess,data.length);dispatch_semaphore_signal(self.completed);});return YES;
}
@end
int main(void) {@autoreleasepool {
    gMIDIQueue=dispatch_queue_create("midi.contract.test",DISPATCH_QUEUE_SERIAL);
    FakeMIDIPipe *pipe=[FakeMIDIPipe new];pipe.received=[NSMutableData data];pipe.completed=dispatch_semaphore_create(0);
    MboxMIDITransport *transport=[MboxMIDITransport new];
    [transport setValue:pipe forKey:@"output"];[transport setValue:pipe forKey:@"input"];
    [transport setValue:[NSMutableData data] forKey:@"encoded"];
    [transport setValue:[NSMutableArray array] forKey:@"pending"];
    mach_timebase_info_data_t tb;mach_timebase_info(&tb);
    [transport setValue:@((double)tb.numer/tb.denom) forKey:@"nsPerTick"];
    NSMutableArray *buffers=[NSMutableArray array];
    for(NSUInteger n=4;n<=16;n+=4)[buffers addObject:[[FixedMIDIData alloc] initWithSize:n]];
    [transport setValue:buffers forKey:@"writeBuffers"];
    for(NSUInteger messages=1;messages<=70;messages++) {
        NSMutableData *input=[NSMutableData data],*expected=[NSMutableData data];
        for(NSUInteger i=0;i<messages;i++) {uint8_t raw[]={0x8f,(uint8_t)(i%128),0},wire[]={0x8f,(uint8_t)(i%128),0,3};
            [input appendBytes:raw length:3];[expected appendBytes:wire length:4];}
        dispatch_sync(gMIDIQueue,^{[pipe.received setLength:0];assert([transport send:input timestamp:0]);});
        for(NSUInteger i=0;i<(messages+3)/4;i++)assert(!dispatch_semaphore_wait(pipe.completed,dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC)));
        dispatch_sync(gMIDIQueue,^{assert([pipe.received isEqualToData:expected]);assert(![[transport status][@"errors"] unsignedLongLongValue]);});
    }
    // Invalid length and excessive scheduling horizon fail without submitting USB.
    dispatch_sync(gMIDIQueue,^{
        assert(![transport send:[NSMutableData dataWithLength:4097] timestamp:0]);
        uint8_t raw[]={0x8f,1,0};NSData *data=[NSData dataWithBytes:raw length:3];
        assert(![transport send:data timestamp:mach_absolute_time()+(uint64_t)(31e9*tb.denom/tb.numer)]);
        pipe.reject=YES;[transport send:data timestamp:0];assert(![[transport status][@"online"] boolValue]);
    });
    puts("Native MIDI immutable buffers, asynchronous lifetime, queue bounds and failed enqueue passed");return 0;
}}
