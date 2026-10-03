// SPDX-License-Identifier: MIT
#ifndef MBOX_SHARED_H
#define MBOX_SHARED_H
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <math.h>
#define MBOX_MACH_SERVICE "audio.necromancer.mbox2.transport"
#define MBOX_SHARED_MAGIC UINT64_C(0x4d424f5832434131)
#define MBOX_RING_FRAMES 32768u
#define MBOX_CLOCK_PERIOD 512u
#define MBOX_SHARED_VERSION 2u
// Tagged frames support independent timestamped readers without consuming input.
// All interprocess accesses use lock-free, naturally aligned atomics.
typedef struct { uint64_t tag, generation; uint32_t left, right; } MboxSharedFrame;
typedef struct {
    uint64_t magic, version, generation, online, heartbeat, clients;
    uint64_t clock_seq, clock_sample, clock_host;
    uint64_t output_written, output_consumed, output_missed, input_written;
    uint64_t output_valid, output_nonzero, hal_write_calls, hal_read_calls, hal_read_missed;
    uint64_t hal_write_frame, hal_write_count, zero_sample, zero_host, zero_query;
    uint64_t playback_packets, capture_packets, feedback_valid, iso_errors;
    MboxSharedFrame output[MBOX_RING_FRAMES];
    MboxSharedFrame input[MBOX_RING_FRAMES];
} MboxShared;
static inline uint64_t mbox_load(const uint64_t *p){return __atomic_load_n(p,__ATOMIC_ACQUIRE);}
static inline void mbox_store(uint64_t *p,uint64_t v){__atomic_store_n(p,v,__ATOMIC_RELEASE);}
static inline void mbox_ring_write(MboxSharedFrame *ring,uint64_t index,float l,float r,uint64_t generation){
    MboxSharedFrame *f=&ring[index&(MBOX_RING_FRAMES-1)];uint32_t lb,rb;
    l=isfinite(l)?fmaxf(-1,fminf(1,l)):0;r=isfinite(r)?fmaxf(-1,fminf(1,r)):0;
    memcpy(&lb,&l,4);memcpy(&rb,&r,4);mbox_store(&f->tag,0);mbox_store(&f->generation,generation);
    __atomic_store_n(&f->left,lb,__ATOMIC_RELAXED);__atomic_store_n(&f->right,rb,__ATOMIC_RELAXED);
    mbox_store(&f->tag,index+1);
}
static inline bool mbox_ring_read(const MboxSharedFrame *ring,uint64_t index,float *l,float *r,uint64_t generation){
    const MboxSharedFrame *f=&ring[index&(MBOX_RING_FRAMES-1)];
    if(mbox_load(&f->tag)!=index+1 || mbox_load(&f->generation)!=generation){*l=*r=0;return false;}
    uint32_t lb=__atomic_load_n(&f->left,__ATOMIC_RELAXED),rb=__atomic_load_n(&f->right,__ATOMIC_RELAXED);
    if(mbox_load(&f->tag)!=index+1 || mbox_load(&f->generation)!=generation){*l=*r=0;return false;}
    memcpy(l,&lb,4);memcpy(r,&rb,4);
    if(!isfinite(*l) || !isfinite(*r)){*l=*r=0;return false;}return true;
}
#endif
