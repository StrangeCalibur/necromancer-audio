// SPDX-License-Identifier: MIT
#ifndef MBOX_OPTIONS_H
#define MBOX_OPTIONS_H
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#define MBOX_VERSION "0.1.0-alpha.2"
#define MBOX_VENDOR 0x0dba
#define MBOX_PRODUCT 0x3000
#define MBOX_FIRMWARE 0x0143

typedef enum { MBOX_HELP, MBOX_VERSION_MODE, MBOX_LIST, MBOX_INSPECT, MBOX_SERVE } MboxMode;
typedef struct { MboxMode mode; bool has_location, midi; uint32_t location; } MboxOptions;

static inline bool mbox_parse_options(int argc, const char **argv, MboxOptions *o) {
    *o=(MboxOptions){.mode=MBOX_HELP};
    if(argc<2)return true;
    if(!strcmp(argv[1],"--help"))o->mode=MBOX_HELP;
    else if(!strcmp(argv[1],"--version"))o->mode=MBOX_VERSION_MODE;
    else if(!strcmp(argv[1],"--list"))o->mode=MBOX_LIST;
    else if(!strcmp(argv[1],"--inspect"))o->mode=MBOX_INSPECT;
    else if(!strcmp(argv[1],"--serve-capture"))o->mode=MBOX_SERVE;
    else return false;
    for(int i=2;i<argc;i++) {
        if(!strcmp(argv[i],"--location-id")) {
            if(o->has_location || ++i>=argc)return false;
            const char *s=argv[i]; char *end=NULL;
            if(s[0]<'0' || s[0]>'9')return false;
            errno=0;unsigned long long n=strtoull(s,&end,0);
            if(errno || *end || n>UINT32_MAX)return false;
            o->has_location=true;o->location=(uint32_t)n;
        } else if(!strcmp(argv[i],"--enable-midi") && !o->midi)o->midi=true;
        else return false;
    }
    return (!o->midi || o->mode==MBOX_SERVE) &&
        ((!o->has_location && !o->midi) || o->mode==MBOX_SERVE || o->mode==MBOX_INSPECT);
}

// Match only the original Mbox 2 runtime profile; bootloaders and variants are excluded.
static inline bool mbox_candidate(long vendor, long product, long revision, long location,
                                  const MboxOptions *o) {
    return vendor==MBOX_VENDOR && product==MBOX_PRODUCT && revision==MBOX_FIRMWARE &&
        location>=0 && (uint64_t)location<=UINT32_MAX &&
        (!o->has_location || (uint32_t)location==o->location);
}
#endif
