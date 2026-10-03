// SPDX-License-Identifier: MIT
#include "mbox_midi_codec.h"
#include <assert.h>
#include <stdio.h>
typedef struct {uint8_t bytes[4096];size_t count,events;uint64_t time[4096];} Capture;
static void capture(void *ctx,const uint8_t *bytes,size_t n,uint64_t time) {
    Capture *c=ctx;assert(n>=1 && n<=3 && c->count+n<=sizeof(c->bytes));
    uint8_t wire[4],decoded[12];size_t count=0;
    assert(mbox_midi_encode(wire,bytes,n));assert(wire[3]==n);
    assert(mbox_midi_decode(wire,4,decoded,&count));assert(count==n && !memcmp(bytes,decoded,n));
    memcpy(c->bytes+c->count,bytes,n);c->count+=n;c->time[c->events++]=time;
}
int main(void) {
    // Fragmented channel messages, running status and interleaved real time.
    MboxMIDIParser p={0};Capture c={0};uint8_t a[]={0x91,60},b[]={0xf8,64,61,65,0xc1,17,18,0xf2,1,2};
    mbox_midi_feed(&p,a,sizeof(a),100,capture,&c);assert(c.count==0);
    mbox_midi_feed(&p,b,sizeof(b),200,capture,&c);
    uint8_t expected[]={0xf8,0x91,60,64,0x91,61,65,0xc1,17,0xc1,18,0xf2,1,2};
    assert(c.count==sizeof(expected) && !memcmp(c.bytes,expected,sizeof(expected)));
    assert(c.time[0]==200 && c.time[1]==100);
    // System common clears running status. Orphan bytes and undefined status are dropped.
    size_t prior=c.count;uint8_t orphan[]={20,21,0xf4,1,2};
    mbox_midi_feed(&p,orphan,sizeof(orphan),300,capture,&c);assert(c.count==prior);
    // Long SysEx across every possible split; all message bytes must be retained.
    uint8_t sysex[259];sysex[0]=0xf0;for(size_t i=1;i<258;i++)sysex[i]=(uint8_t)(i%128);sysex[258]=0xf7;
    for(size_t split=0;split<=sizeof(sysex);split++) {
        memset(&p,0,sizeof(p));memset(&c,0,sizeof(c));
        mbox_midi_feed(&p,sysex,split,1,capture,&c);
        mbox_midi_feed(&p,sysex+split,sizeof(sysex)-split,2,capture,&c);
        assert(c.count==sizeof(sysex) && !memcmp(c.bytes,sysex,sizeof(sysex)));
        assert(!p.sysex && !p.count);
    }
    uint8_t invalid[]={0x90,1,2,0x13},out[12];size_t n;
    assert(!mbox_midi_decode(invalid,4,out,&n));assert(!n);
    assert(!mbox_midi_decode(invalid,3,out,&n));
    assert(!mbox_midi_encode(out,invalid,4));
    // All one-byte boundaries and arbitrary malformed streams stay bounded.
    uint32_t rng=17;memset(&p,0,sizeof(p));
    for(size_t i=0;i<200000;i++) {rng=rng*1664525u+1013904223u;uint8_t v=rng>>24;
        memset(&c,0,sizeof(c));mbox_midi_feed(&p,&v,1,i,capture,&c);assert(p.count<=2);}
    puts("MIDI framing, running status, SysEx, malformed packets and randomized bounds passed");return 0;
}
