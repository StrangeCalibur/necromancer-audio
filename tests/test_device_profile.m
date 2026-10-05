// SPDX-License-Identifier: MIT
// The actual descriptor validator is tested without enumerating/opening USB.
#define main mboxNativeProgramMain
#include "mbox_native.m"
#undef main
#include <assert.h>
static unsigned allocationCalls;
@interface MboxMissingAllocator : NSObject @end
@implementation MboxMissingAllocator @end
@interface MboxAvailableAllocator : NSObject
- (NSMutableData *)dataWithCapacity:(NSUInteger)capacity options:(NSUInteger)options error:(NSError **)error;
@end
@implementation MboxAvailableAllocator
- (NSMutableData *)dataWithCapacity:(NSUInteger)capacity options:(NSUInteger)options error:(NSError **)error {
    allocationCalls++;return nil;
}
@end
int main(void){@autoreleasepool{
    assert(!mbox_runtime_has_shared_allocator([MboxMissingAllocator class]));
    assert(mbox_runtime_has_shared_allocator([MboxAvailableAllocator class]));
    assert(allocationCalls==0); // The availability probe must not allocate/open hardware.

    NSMutableData *data=[NSMutableData dataWithLength:646];uint8_t *p=data.mutableBytes;
    const uint8_t prefix[]={
        9,2,0x86,2,7,1,0,0x80,50,
        9,4,2,2,2,1,2,0,0,
        11,0x24,2,1,2,3,24,1,0x80,0xbb,0,
        9,5,3,5,0x28,1,1,0,0x83,
        9,5,0x83,1,3,0,1,0,0,
        9,4,4,2,1,1,2,0,0,
        11,0x24,2,1,2,3,24,1,0x80,0xbb,0,
        9,5,0x85,5,0x28,1,1,0,0
    };
    memcpy(p,prefix,sizeof(prefix));
    for(size_t i=sizeof(prefix);i<646;i+=2){p[i]=2;p[i+1]=0x7f;}
    assert(profile(data));
    const size_t fields[]={0,2,4,5,14,15,21,22,23,24,31,32,33,35,37,40,41,42,44,59,60,72};
    for(size_t i=0;i<sizeof(fields)/sizeof(*fields);i++){
        uint8_t prior=p[fields[i]];p[fields[i]]^=0x40;assert(!profile(data));p[fields[i]]=prior;
    }
    uint8_t previous=p[76];p[76]=0;assert(!profile(data));p[76]=previous;
    assert(!profile([data subdataWithRange:NSMakeRange(0,645)]));
    puts("PASS: actual USB profile accepts required streams and rejects malformed descriptors/endpoint changes");
}}
