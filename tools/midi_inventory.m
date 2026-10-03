// SPDX-License-Identifier: MIT
#import <Foundation/Foundation.h>
#import <CoreMIDI/CoreMIDI.h>
static NSString *name(MIDIObjectRef object, CFStringRef key) {
    CFStringRef value=NULL;
    return MIDIObjectGetStringProperty(object,key,&value)==noErr && value ? CFBridgingRelease(value) : @"";
}
int main(void) {@autoreleasepool {
    MIDIClientRef client=0; OSStatus status=MIDIClientCreate(CFSTR("Necromancer MIDI inventory"),NULL,NULL,&client);
    if(status){fprintf(stderr,"MIDIClientCreate: %d\n",(int)status);return 1;}
    NSMutableDictionary *result=[NSMutableDictionary dictionary];
    for(int direction=0;direction<2;direction++) {
        NSMutableArray *items=[NSMutableArray array];
        ItemCount count=direction?MIDIGetNumberOfDestinations():MIDIGetNumberOfSources();
        for(ItemCount i=0;i<count;i++) {
            MIDIEndpointRef ep=direction?MIDIGetDestination(i):MIDIGetSource(i);
            SInt32 uid=0,offline=0;MIDIObjectGetIntegerProperty(ep,kMIDIPropertyUniqueID,&uid);
            MIDIObjectGetIntegerProperty(ep,kMIDIPropertyOffline,&offline);
            [items addObject:@{@"name":name(ep,kMIDIPropertyName),@"display_name":name(ep,kMIDIPropertyDisplayName),
                @"manufacturer":name(ep,kMIDIPropertyManufacturer),@"uid":@(uid),@"offline":@(offline)}];
        }
        result[direction?@"destinations":@"sources"]=items;
    }
    NSData *data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];
    fwrite(data.bytes,1,data.length,stdout);puts("");MIDIClientDispose(client);return 0;
}}
