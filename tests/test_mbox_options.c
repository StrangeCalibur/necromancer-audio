// SPDX-License-Identifier: MIT
#include "mbox_options.h"
#include <assert.h>
#include <stdio.h>
#define PARSE(...) do {const char *v[]={"test",__VA_ARGS__};assert(mbox_parse_options(sizeof(v)/sizeof(*v),v,&o));} while(0)
#define REJECT(...) do {const char *v[]={"test",__VA_ARGS__};assert(!mbox_parse_options(sizeof(v)/sizeof(*v),v,&o));} while(0)
int main(void) {
    MboxOptions o;
    PARSE("--serve-capture");assert(!o.has_location && !o.midi);
    assert(mbox_candidate(0x0dba,0x3000,0x143,123,&o));
    assert(mbox_candidate(0x0dba,0x3000,0x143,456,&o));
    assert(!mbox_candidate(0x0dba,0x3001,0x143,123,&o));
    assert(!mbox_candidate(0x0dba,0x3000,0x124,123,&o));
    assert(!mbox_candidate(0x1234,0x3000,0x143,123,&o));
    assert(!mbox_candidate(0x0dba,0x3000,0x143,-1,&o));
    PARSE("--serve-capture","--enable-midi","--location-id","0x1234");
    assert(o.midi && o.location==0x1234);
    assert(mbox_candidate(0x0dba,0x3000,0x143,0x1234,&o));
    assert(!mbox_candidate(0x0dba,0x3000,0x143,0x1235,&o));
    PARSE("--inspect","--location-id","4294967295");assert(o.location==UINT32_MAX);
    REJECT("--serve-capture","--location-id");
    REJECT("--serve-capture","--location-id","4294967296");
    REJECT("--serve-capture","--location-id","-1");
    REJECT("--serve-capture","--location-id","");
    REJECT("--serve-capture","--location-id","1extra");
    REJECT("--serve-capture","--location-id","1","--location-id","2");
    REJECT("--serve-capture","--enable-midi","--enable-midi");
    REJECT("--inspect","--enable-midi");
    REJECT("--list","--location-id","1");
    REJECT("--flash");REJECT("--tone-capture");
    puts("PASS: portable identity matching, optional location pin and fail-closed arguments");
}
