// SPDX-License-Identifier: MIT
// Independent 48 kHz transport primitives; no USB I/O or firmware operations.
#ifndef MBOX_PCM_H
#define MBOX_PCM_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <math.h>

enum { MBOX_BYTES_PER_FRAME = 6, MBOX_PACKET_CAPACITY = 296,
       MBOX_FEEDBACK_FRACTION_BITS = 14, MBOX_SAMPLE_RATE = 48000 };

typedef struct { uint32_t fraction; uint32_t rate; } MboxPacketClock;

// A full-speed explicit-feedback value is three little-endian bytes, 10.14.
// Reject malformed/outlying values instead of turning them into buffer lengths.
static inline bool mbox_accept_feedback(MboxPacketClock *clock,
                                        const uint8_t *bytes, size_t count) {
    if (!clock || !bytes || count != 3) return false;
    uint32_t rate = bytes[0] | ((uint32_t)bytes[1] << 8) | ((uint32_t)bytes[2] << 16);
    if (rate < (47u << 14) || rate > (49u << 14)) return false;
    clock->rate = rate;
    return true;
}

static inline bool mbox_next_packet(MboxPacketClock *clock, size_t *frames) {
    if (!clock || !frames || clock->fraction >= (1u << 14) ||
        clock->rate < (47u << 14) || clock->rate > (49u << 14)) return false;
    uint32_t total = clock->fraction + clock->rate;
    size_t n = total >> 14;
    if (n * MBOX_BYTES_PER_FRAME > MBOX_PACKET_CAPACITY) return false;
    clock->fraction = total & ((1u << 14) - 1);
    *frames = n;
    return true;
}

static inline bool mbox_pack_s24be(uint8_t *destination, int32_t sample) {
    if (!destination || sample < -8388608 || sample > 8388607) return false;
    uint32_t bits = (uint32_t)sample & 0xffffffu;
    destination[0] = (uint8_t)(bits >> 16);
    destination[1] = (uint8_t)(bits >> 8);
    destination[2] = (uint8_t)bits;
    return true;
}

// Fixed short test: stereo 480 Hz, -42 dBFS peak, 100 ms ramps, two seconds.
// Frame positions are sample positions, independent of USB packet boundaries.
static inline bool mbox_test_tone(uint8_t *packet, size_t capacity,
                                  size_t frames, uint64_t first_sample) {
    const uint64_t duration = 2u * MBOX_SAMPLE_RATE;
    const uint64_t ramp = MBOX_SAMPLE_RATE / 10;
    if (!packet || frames > MBOX_PACKET_CAPACITY / MBOX_BYTES_PER_FRAME ||
        capacity < frames * MBOX_BYTES_PER_FRAME) return false;
    for (size_t i = 0; i < frames; i++) {
        uint64_t position = first_sample + i;
        double envelope = 0;
        if (position >= first_sample && position < duration) {
            envelope = fmin(1.0, fmin((double)position / ramp,
                                     (double)(duration - 1 - position) / ramp));
        }
        double angle = 6.28318530717958647692 * (double)(position % 100) / 100.0;
        int32_t sample = (int32_t)lrint(8388607.0 * 0.007943282347242816 * envelope * sin(angle));
        if (!mbox_pack_s24be(packet + i * 6, sample) ||
            !mbox_pack_s24be(packet + i * 6 + 3, sample)) return false;
    }
    return true;
}
#endif
