// SPDX-License-Identifier: MIT
// Independent, single-owner native Mbox 2 transport. No libusb or firmware writes.
#import <Foundation/Foundation.h>
#import <IOUSBHost/IOUSBHost.h>
#import <IOKit/IOKitLib.h>
#import <libkern/OSByteOrder.h>
#include <unistd.h>
#include <string.h>
#include "mbox_pcm.h"
#include "mbox_options.h"

static void checkpoint(NSString *stage, NSDictionary *values) {
    NSMutableDictionary *entry=[values mutableCopy]?:[NSMutableDictionary dictionary];
    entry[@"stage"]=stage;entry[@"utc"]=[[NSISO8601DateFormatter new] stringFromDate:[NSDate date]];
    NSData *data=[NSJSONSerialization dataWithJSONObject:entry options:NSJSONWritingSortedKeys error:nil];
    flockfile(stdout);fwrite(data.bytes,1,data.length,stdout);fputc('\n',stdout);fflush(stdout);fsync(STDOUT_FILENO);funlockfile(stdout);
}
static NSDictionary *failure(NSError *e) {
    return @{@"domain":e.domain?:@"",@"code":@(e.code),@"description":e.localizedDescription?:@"",
             @"reason":e.localizedFailureReason?:@"",@"recovery":e.localizedRecoverySuggestion?:@""};
}
static long property(io_service_t s, CFStringRef name) {
    CFTypeRef v=IORegistryEntryCreateCFProperty(s,name,kCFAllocatorDefault,0);long n=-1;
    if(v && CFGetTypeID(v)==CFNumberGetTypeID()) CFNumberGetValue(v,kCFNumberLongType,&n);
    if(v)CFRelease(v);return n;
}
static uint16_t le16(const uint8_t *p) { return p[0] | ((uint16_t)p[1] << 8); }
static NSString *hex(NSData *data) {
    NSMutableString *s=[NSMutableString string]; const uint8_t *p=data.bytes;
    for(NSUInteger i=0;i<data.length;i++) [s appendFormat:@"%02x",p[i]];
    return s;
}
static NSData *control(IOUSBHostDevice *dev, NSMutableArray *log, uint8_t type,
                       uint8_t code, uint16_t value, uint16_t index,
                       NSUInteger length, NSData *payload) {
    IOUSBDeviceRequest req={.bmRequestType=type,.bRequest=code,
        .wValue=OSSwapHostToLittleInt16(value),.wIndex=OSSwapHostToLittleInt16(index),
        .wLength=OSSwapHostToLittleInt16((uint16_t)length)};
    NSMutableData *data=payload?[payload mutableCopy]:[NSMutableData dataWithLength:length];
    if(data.length!=length) return nil;
    NSUInteger actual=0; NSError *error=nil;
    checkpoint(@"control.begin",@{@"type":@(type),@"request":@(code),@"value":@(value),@"index":@(index),@"length":@(length)});
    BOOL ok=[dev sendDeviceRequest:req data:data bytesTransferred:&actual completionTimeout:2 error:&error];
    NSMutableDictionary *e=[@{@"type":@(type),@"request":@(code),@"value":@(value),
        @"index":@(index),@"length":@(length),@"actual":@(actual),@"ok":@(ok)} mutableCopy];
    if(error) {e[@"error"]=error.localizedDescription; e[@"code"]=@(error.code);e[@"reason"]=error.localizedFailureReason?:@"";}
    if(ok && actual<=length) {data.length=actual;e[@"hex"]=hex(data);}
    [log addObject:e]; checkpoint(@"control.end",e); return ok && actual<=length?data:nil;
}

static BOOL profile(NSData *data) {
    const uint8_t *p=data.bytes;
    if(data.length!=646 || p[0]!=9 || p[1]!=2 || le16(p+2)!=646 || p[4]!=7 || p[5]!=1) return NO;
    int number=-1, alternate=-1; BOOL out=NO, feedback=NO, input=NO, formatOut=NO, formatIn=NO;
    for(NSUInteger offset=9;offset<data.length;) {
        const uint8_t *d=p+offset; NSUInteger n=d[0];
        if(n<2 || n>data.length-offset) return NO;
        if(d[1]==4) {
            if(n!=9) return NO;
            number=d[2];alternate=d[3];
            if(alternate==2 && (number==2 || number==4) && (d[5]!=1 || d[6]!=2)) return NO;
        } else if(d[1]==0x24 && n>=7 && d[2]==2 && alternate==2) {
            BOOL valid=d[3]==1 && d[4]==2 && d[5]==3 && d[6]==24;
            if(number==2) formatOut=valid;
            if(number==4) formatIn=valid;
        } else if(d[1]==5 && alternate==2) {
            if(n!=9) return NO;
            if(number==2 && d[2]==3) out=d[3]==5 && le16(d+4)==296 && d[6]==1 && d[8]==0x83;
            if(number==2 && d[2]==0x83) feedback=d[3]==1 && le16(d+4)==3 && d[6]==1;
            if(number==4 && d[2]==0x85) input=d[3]==5 && le16(d+4)==296 && d[6]==1;
        }
        offset+=n;
    }
    return out && feedback && input && formatOut && formatIn;
}

static IOUSBHostInterface *openInterface(io_service_t device, NSUInteger number,
                                         dispatch_queue_t queue, IOUSBHostObjectInitOptions options,
                                         NSError **error) {
    io_iterator_t iter=IO_OBJECT_NULL;
    kern_return_t result=IORegistryEntryCreateIterator(device,kIOServicePlane,kIORegistryIterateRecursively,&iter);
    if(result!=KERN_SUCCESS) return nil;
    io_service_t target=IO_OBJECT_NULL, item; NSUInteger matches=0;
    while((item=IOIteratorNext(iter))) {
        if(IOObjectConformsTo(item,"IOUSBHostInterface")) {
            CFTypeRef value=IORegistryEntryCreateCFProperty(item,CFSTR("bInterfaceNumber"),kCFAllocatorDefault,0);
            BOOL found=value && CFGetTypeID(value)==CFNumberGetTypeID() &&
                         [(__bridge NSNumber *)value unsignedIntegerValue]==number;
            if(value) CFRelease(value);
            if(found) {matches++;if(matches==1) {target=item;continue;}}
        }
        IOObjectRelease(item);
    }
    IOObjectRelease(iter);
    IOUSBHostInterface *interface=nil;
    if(matches==1) interface=[[IOUSBHostInterface alloc] initWithIOService:target
        options:options queue:queue error:error interestHandler:nil];
    if(target) IOObjectRelease(target);
    return interface;
}

#include "mbox_midi_transport.h"
#include "mbox_service.h"
#include "mbox_duplex.h"

static int runDevice(const MboxOptions *options) {
    @autoreleasepool {
        BOOL serve=options->mode==MBOX_SERVE;
        BOOL capture=serve;
        if(capture && geteuid()!=0){fprintf(stderr,"Native device capture requires macOS administrator authentication. No device opened.\n");return 3;}
        checkpoint(@"start",@{@"capture":@(capture),@"firmware_write":@NO,@"audio_streamed":@NO});
        io_iterator_t iter=IO_OBJECT_NULL;io_service_t target=IO_OBJECT_NULL;NSUInteger matches=0;
        CFMutableDictionaryRef match=[IOUSBHostDevice createMatchingDictionaryWithVendorID:@0x0dba productID:@0x3000
            bcdDevice:nil deviceClass:nil deviceSubclass:nil deviceProtocol:nil speed:nil productIDArray:nil];
        kern_return_t kr=IOServiceGetMatchingServices(kIOMainPortDefault,match,&iter);
        if(kr!=KERN_SUCCESS){checkpoint(@"enumeration.failed",@{@"code":@(kr)});return 1;}
        io_service_t item;
        while((item=IOIteratorNext(iter))) {
            long vendor=property(item,CFSTR("idVendor")),product=property(item,CFSTR("idProduct"));
            long revision=property(item,CFSTR("bcdDevice")),location=property(item,CFSTR("locationID"));
            BOOL eligible=mbox_candidate(vendor,product,revision,location,options);
            checkpoint(@"device.found",@{@"vendor":@(vendor),@"product":@(product),@"revision":@(revision),@"location":@(location),@"eligible":@(eligible)});
            if(eligible){matches++;if(matches==1){target=item;continue;}}
            IOObjectRelease(item);
        }
        IOObjectRelease(iter);
        if(options->mode==MBOX_LIST){if(target)IOObjectRelease(target);checkpoint(@"enumeration.complete",@{@"eligible_devices":@(matches),@"usb_opened":@NO});return 0;}
        // Never choose arbitrarily among multiple devices. A location pin is optional.
        if(matches!=1){checkpoint(@"identity.rejected",@{@"matches":@(matches),@"reason":matches?@"multiple supported devices; use --location-id":@"no supported firmware 1.43 device"});if(target)IOObjectRelease(target);return 1;}
        checkpoint(@"identity.verified",@{@"vendor":@MBOX_VENDOR,@"product":@MBOX_PRODUCT,@"revision":@MBOX_FIRMWARE,@"location":@(property(target,CFSTR("locationID")))});
        dispatch_queue_t queue=dispatch_queue_create("audio.necromancer.mbox.native",
            dispatch_queue_attr_make_with_qos_class(DISPATCH_QUEUE_SERIAL,QOS_CLASS_USER_INTERACTIVE,0));
        NSError *error=nil;BOOL success=NO;
        checkpoint(@"device.open.begin",@{@"exclusive_capture":@(capture)});
        IOUSBHostDevice *dev=[[IOUSBHostDevice alloc] initWithIOService:target
            options:capture?IOUSBHostObjectInitOptionsDeviceCapture:IOUSBHostObjectInitOptionsNone
            queue:queue error:&error interestHandler:nil];
        checkpoint(@"device.open.end",dev?@{@"ok":@YES}:failure(error));
        IOUSBHostInterface *play=nil,*input=nil;
        MboxMIDITransport *midi=nil;
        if(dev) @try {do {
            NSMutableArray *log=[NSMutableArray array];
            NSData *d=control(dev,log,0x80,6,0x100,0,18,nil);
            const uint8_t *p=d.bytes;
            if(d.length!=18 || le16(p+8)!=0x0dba || le16(p+10)!=0x3000 || le16(p+12)!=0x143)break;
            NSData *cfg=control(dev,log,0x80,6,0x200,0,646,nil);
            if(!profile(cfg)){checkpoint(@"profile.rejected",nil);break;}
            checkpoint(@"profile.verified",nil);
            NSData *active=control(dev,log,0x80,8,0,0,1,nil);
            const IOUSBConfigurationDescriptor *cached=dev.configurationDescriptor;
            checkpoint(@"configuration.initial",@{@"device_value":active.length?@(*(const uint8_t *)active.bytes):@(-1),
                @"host_value":cached?@(cached->bConfigurationValue):@(-1)});
            if(!capture){success=YES;break;}
            BOOL ready=NO;
            for(unsigned poll=0;poll<10;poll++){
                [NSThread sleepForTimeInterval:0.5];
                NSData *s=control(dev,log,0xc0,0x85,1,0,18,nil);
                if(!s.length)break;uint8_t state=*(const uint8_t *)s.bytes;
                if(state==2){ready=YES;break;}if(state!=1)break;
            }
            if(!ready){checkpoint(@"boot.failed",nil);break;}
            active=control(dev,log,0x80,8,0,0,1,nil);
            cached=dev.configurationDescriptor;
            if(active.length!=1 || *(const uint8_t *)active.bytes>1){checkpoint(@"configuration.invalid",nil);break;}
            // Runtime activation resets device configuration without updating the host cache.
            // Under exclusive native ownership, first reconcile the host to unconfigured.
            // No interface handle exists yet; never hand this transition to legacy IOKit.
            if(*(const uint8_t *)active.bytes==0 && cached && cached->bConfigurationValue==1){
                checkpoint(@"configuration.reconcile.begin",@{@"value":@0});
                BOOL reconciled=[dev configureWithValue:0 matchInterfaces:NO error:&error];
                checkpoint(@"configuration.reconcile.end",reconciled?@{@"ok":@YES}:failure(error));
                if(!reconciled)break;
            }
            checkpoint(@"configuration.select.begin",@{@"value":@1,@"match_interfaces":@NO});
            BOOL configured=[dev configureWithValue:1 matchInterfaces:NO error:&error];
            checkpoint(@"configuration.select.end",configured?@{@"ok":@YES}:failure(error));
            if(!configured)break;
            active=control(dev,log,0x80,8,0,0,1,nil);
            cached=dev.configurationDescriptor;
            checkpoint(@"configuration.selected",@{@"device_value":active.length?@(*(const uint8_t *)active.bytes):@(-1),
                @"host_value":cached?@(cached->bConfigurationValue):@(-1)});
            if(active.length!=1 || *(const uint8_t *)active.bytes!=1 || !cached || cached->bConfigurationValue!=1){
                checkpoint(@"configuration.inconsistent",nil);break;
            }
            for(NSUInteger attempt=0;attempt<20;attempt++) {
                checkpoint(@"interface2.open.begin",@{@"attempt":@(attempt)});
                error=nil;play=openInterface(target,2,queue,IOUSBHostObjectInitOptionsNone,&error);
                checkpoint(@"interface2.open.end",play?@{@"ok":@YES}:failure(error));
                if(play || error)break;[NSThread sleepForTimeInterval:0.025];
            }
            if(!play)break;
            checkpoint(@"interface4.open.begin",nil);
            input=openInterface(target,4,queue,IOUSBHostObjectInitOptionsNone,&error);
            checkpoint(@"interface4.open.end",input?@{@"ok":@YES}:failure(error));if(!input)break;
            checkpoint(@"alternate2.select.begin",nil);
            if(![play selectAlternateSetting:2 error:&error] || ![input selectAlternateSetting:2 error:&error]){
                checkpoint(@"alternate2.select.failed",failure(error));break;
            }
            checkpoint(@"alternate2.select.end",@{@"ok":@YES});
            const uint8_t rate[]={0x80,0xbb,0};
            NSData *sent=control(dev,log,0x22,1,0x100,0x85,3,[NSData dataWithBytes:rate length:3]);
            if(sent.length!=3)break;
            NSData *readback=control(dev,log,0xa2,0x81,0x100,0x85,3,nil);
            if(readback.length!=3 || memcmp(readback.bytes,rate,3)!=0)break;
            checkpoint(@"pipes.open.begin",nil);
            IOUSBHostPipe *outPipe=[play copyPipeWithAddress:3 error:&error];
            IOUSBHostPipe *feedback=[play copyPipeWithAddress:0x83 error:&error];
            IOUSBHostPipe *inPipe=[input copyPipeWithAddress:0x85 error:&error];
            success=outPipe && feedback && inPipe;
            checkpoint(@"pipes.open.end",success?@{@"ok":@YES,@"rate":@48000}:failure(error));
            if(success && serve){
                if(options->midi) {
                    midi=[MboxMIDITransport new];
                    if([midi start:target])dispatch_sync(gMIDIQueue,^{gMIDITransport=midi;});
                    else {[midi stop];midi=nil;}
                }
                MboxDuplex *stream=[[MboxDuplex alloc] initWithDevice:dev pipes:@[outPipe,feedback,inPipe] queue:queue];
                if(serve)[stream setBridge:gShared];
                success=[[stream run][@"success"] boolValue];
            }
        }while(NO);} @finally {
            if(midi){dispatch_sync(gMIDIQueue,^{gMIDITransport=nil;});[midi stop];}
            if(input){checkpoint(@"interface4.close.begin",nil);[input selectAlternateSetting:0 error:nil];[input destroy];}
            if(play){checkpoint(@"interface2.close.begin",nil);[play selectAlternateSetting:0 error:nil];[play destroy];}
            checkpoint(@"device.close.begin",@{@"reset_and_rematch":@(capture)});[dev destroy];
            checkpoint(@"device.close.end",nil);
        }
        IOObjectRelease(target);checkpoint(@"finished",@{@"success":@(success)});return success?0:1;
    }
}

// Probe availability before creating IPC, capturing USB or initializing the device.
static BOOL mbox_runtime_has_shared_allocator(Class host) {
    return [host instancesRespondToSelector:@selector(dataWithCapacity:options:error:)];
}

int main(int argc,const char **argv){
    @autoreleasepool {
        MboxOptions options;
        if(!mbox_parse_options(argc,argv,&options)){fprintf(stderr,"Invalid arguments; run --help. No device opened.\n");return 2;}
        if(options.mode==MBOX_VERSION_MODE){puts(MBOX_VERSION);return 0;}
        if(options.mode==MBOX_HELP){puts("Usage: mbox_service --list | --inspect [--location-id ID] | --serve-capture [--location-id ID] [--enable-midi]\n--list reads USB registry metadata only. --inspect reads descriptors without initialization.\n--serve-capture requires administrator privileges, captures the selected Mbox, initializes audio and streams continuously. Stopping resets/rematches it.\nSupports one original Mbox 2 with firmware 1.43; multiple matches require an explicit location ID. MIDI is experimental and disabled by default. No firmware writes.");return 0;}
        if(options.mode!=MBOX_SERVE)return runDevice(&options);
        if(!mbox_runtime_has_shared_allocator([IOUSBHostObject class])){
            fprintf(stderr,"This macOS runtime lacks the required IOUSBHost shared-buffer allocator. No device opened.\n");return 3;
        }
        if(!startService()){checkpoint(@"service.start.failed",nil);return 1;}
        while(!gStop){@autoreleasepool{runDevice(&options);mbox_store(&gShared->online,0);}
            for(int i=0;i<30 && !gStop;i++)usleep(100000);
        }
        mbox_store(&gShared->online,0);return 0;
    }
}
