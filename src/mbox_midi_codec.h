// SPDX-License-Identifier: MIT
// Independently authored MIDI 1.0 stream framing and Mbox MIDIMAN wire codec.
#ifndef MBOX_MIDI_CODEC_H
#define MBOX_MIDI_CODEC_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef void (*MboxMIDIEmit)(void *,const uint8_t *,size_t,uint64_t);
typedef struct {
    uint8_t bytes[3],count,expected,running;
    bool sysex;
    uint64_t timestamp;
} MboxMIDIParser;
static inline uint8_t mbox_midi_length(uint8_t status) {
    if(status<0x80)return 0;
    if(status<0xf0)return (status&0xe0)==0xc0?2:3;
    if(status==0xf1 || status==0xf3)return 2;
    if(status==0xf2)return 3;
    return status==0xf6 || status>=0xf8?1:0;
}
static inline void mbox_midi_feed(MboxMIDIParser *p,const uint8_t *bytes,size_t length,
                                  uint64_t timestamp,MboxMIDIEmit emit,void *context) {
    for(size_t i=0;i<length;i++) {
        uint8_t b=bytes[i];
        if(b>=0xf8) {emit(context,&b,1,timestamp);continue;}
        if(b&0x80) {
            if(b==0xf7 && p->sysex) {
                if(!p->count)p->timestamp=timestamp;
                p->bytes[p->count++]=b;emit(context,p->bytes,p->count,p->timestamp);
                memset(p,0,sizeof(*p));continue;
            }
            p->count=0;p->sysex=b==0xf0;p->running=b<0xf0?b:0;
            p->expected=mbox_midi_length(b);p->timestamp=timestamp;
            if(p->sysex || p->expected) {p->bytes[0]=b;p->count=1;}
            if(p->expected==1) {emit(context,p->bytes,1,timestamp);p->count=0;p->expected=0;}
            continue;
        }
        if(p->sysex) {
            if(!p->count)p->timestamp=timestamp;
            p->bytes[p->count++]=b;
            if(p->count==3) {emit(context,p->bytes,3,p->timestamp);p->count=0;}
        } else {
            if(!p->count && p->running) {
                p->bytes[0]=p->running;p->count=1;p->expected=mbox_midi_length(p->running);p->timestamp=timestamp;
            }
            if(!p->count || !p->expected)continue;
            p->bytes[p->count++]=b;
            if(p->count==p->expected) {emit(context,p->bytes,p->count,p->timestamp);p->count=0;p->expected=0;}
        }
    }
}
static inline bool mbox_midi_encode(uint8_t wire[4],const uint8_t *bytes,size_t length) {
    if(length<1 || length>3)return false;
    memset(wire,0,4);memcpy(wire,bytes,length);wire[3]=(uint8_t)length;return true;
}
// Fail the whole transfer on an unknown cable/control or a partial USB packet.
static inline bool mbox_midi_decode(const uint8_t *wire,size_t length,uint8_t *bytes,size_t *count) {
    *count=0;if(length>16 || length%4)return false;
    for(size_t i=0;i<length;i+=4)if(wire[i+3]>3)return false;
    for(size_t i=0;i<length;i+=4) {size_t n=wire[i+3];memcpy(bytes+*count,wire+i,n);*count+=n;}
    return true;
}
#endif
