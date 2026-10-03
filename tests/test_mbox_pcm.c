// SPDX-License-Identifier: MIT
// USB-free checks for byte order, negative samples, packet bounds and drift.
#include "mbox_pcm.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static int32_t unpack(const uint8_t *p) {
    uint32_t u = ((uint32_t)p[0] << 16) | ((uint32_t)p[1] << 8) | p[2];
    return (u & 0x800000u) ? (int32_t)(u - 0x1000000u) : (int32_t)u;
}

int main(void) {
    const int32_t samples[] = {0, 1, -1, 8388607, -8388608, 0x123456, -0x123456};
    uint8_t bytes[3];
    for (size_t i = 0; i < sizeof(samples) / sizeof(samples[0]); i++) {
        assert(mbox_pack_s24be(bytes, samples[i]));
        assert(unpack(bytes) == samples[i]);
    }
    assert(mbox_pack_s24be(bytes, 0x123456));
    assert(memcmp(bytes, (uint8_t[]){0x12, 0x34, 0x56}, 3) == 0);
    assert(!mbox_pack_s24be(bytes, 8388608));
    assert(!mbox_pack_s24be(bytes, -8388609));

    MboxPacketClock clock = {0};
    const uint8_t nominal[] = {0x00, 0x00, 0x0c}; // 48 << 14
    assert(mbox_accept_feedback(&clock, nominal, 3));
    size_t frames;
    for (unsigned i = 0; i < 10000; i++) {
        assert(mbox_next_packet(&clock, &frames));
        assert(frames == 48);
    }
    // Fractional rates must accumulate rather than being rounded per packet.
    const uint32_t rates[] = {(48u << 14) - 1, (48u << 14) + 1,
                              (47u << 14), (49u << 14), (48u << 14) + 8192};
    for (size_t r = 0; r < sizeof(rates) / sizeof(rates[0]); r++) {
        uint32_t rate = rates[r];
        uint8_t feedback[] = {(uint8_t)rate, (uint8_t)(rate >> 8), (uint8_t)(rate >> 16)};
        clock.fraction = 0;
        assert(mbox_accept_feedback(&clock, feedback, 3));
        uint64_t actual = 0;
        for (unsigned i = 0; i < 20000; i++) {
            assert(mbox_next_packet(&clock, &frames));
            assert(frames >= 47 && frames <= 49 && frames * 6 <= 296);
            actual += frames;
        }
        assert(actual == ((uint64_t)rate * 20000) / (1u << 14));
    }
    MboxPacketClock saved = clock;
    assert(!mbox_accept_feedback(&clock, nominal, 2));
    assert(!mbox_accept_feedback(&clock, (uint8_t[]){0, 0, 0}, 3));
    assert(!mbox_accept_feedback(&clock, (uint8_t[]){255, 255, 255}, 3));
    assert(memcmp(&saved, &clock, sizeof(clock)) == 0);
    clock.fraction = 1u << 14;
    assert(!mbox_next_packet(&clock, &frames));

    uint8_t packet[300];
    memset(packet, 0xa5, sizeof(packet));
    assert(!mbox_test_tone(packet, 293, 49, 0));
    assert(!mbox_test_tone(packet, sizeof(packet), 50, 0));
    int32_t peak = 0;
    for (uint64_t position = 0; position < 96000 + 100; position += 49) {
        assert(mbox_test_tone(packet, sizeof(packet), 49, position));
        for (size_t i = 0; i < 49; i++) {
            int32_t sample = unpack(packet + i * 6);
            assert(sample == unpack(packet + i * 6 + 3));
            int32_t magnitude = sample < 0 ? -sample : sample;
            if (magnitude > peak) peak = magnitude;
            assert(magnitude <= 66634);
            if (position + i >= 96000) assert(sample == 0);
        }
        assert(packet[294] == 0xa5 && packet[299] == 0xa5);
    }
    assert(peak > 66000);
    assert(mbox_test_tone(packet, sizeof(packet), 49, UINT64_MAX - 2));
    for (size_t i = 0; i < 49 * 6; i++) assert(packet[i] == 0);
    puts("PASS: BE24 signed boundaries, validated feedback, fractional clock, packet bounds, quiet stereo tone");
    return 0;
}
