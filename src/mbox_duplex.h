// SPDX-License-Identifier: MIT
// Finite single-queue duplex transport. All buffers survive their completion/abort.
@interface MboxIsoSlot : NSObject
@property(nonatomic) IOUSBHostPipe *pipe;
@property(nonatomic) NSMutableData *data;
@property(nonatomic) NSMutableData *storage;
@property(nonatomic) unsigned kind; // 0 playback, 1 feedback, 2 capture
@property(nonatomic) uint64_t packet;
@end
@implementation MboxIsoSlot
@end

@interface MboxDuplex : NSObject {
    IOUSBHostDevice *_device;
    NSArray<IOUSBHostPipe *> *_pipes;
    dispatch_queue_t _queue;
    dispatch_semaphore_t _done;
    NSMutableArray<MboxIsoSlot *> *_slots;
    NSMutableData *_capture;
    MboxPacketClock _clock;
    uint64_t _baseFrame, _next[3], _toneSample, _outputSample, _inputSample, _nextZero, _anchorHost;
    double _ticksPerMillisecond;
    MboxShared *_bridge;
    NSUInteger _outstanding, _good[3], _bad[3], _bytes[3], _feedbackCount;
    int32_t _capturePeak;
    BOOL _stopping, _failed, _signalled;
}
- (instancetype)initWithDevice:(IOUSBHostDevice *)device pipes:(NSArray<IOUSBHostPipe *> *)pipes queue:(dispatch_queue_t)queue;
- (void)setBridge:(MboxShared *)bridge;
- (NSDictionary *)run;
@end
@implementation MboxDuplex
- (instancetype)initWithDevice:(IOUSBHostDevice *)device pipes:(NSArray<IOUSBHostPipe *> *)pipes queue:(dispatch_queue_t)queue {
    if((self=[super init])){_device=device;_pipes=pipes;_queue=queue;_done=dispatch_semaphore_create(0);
        _slots=[NSMutableArray array];_capture=[NSMutableData data];_clock=(MboxPacketClock){0,48u<<14};}
    return self;
}
- (void)setBridge:(MboxShared *)bridge {_bridge=bridge;}
- (void)finishIfDrained {
    if(_outstanding==0 && !_signalled){_signalled=YES;dispatch_semaphore_signal(_done);}
}
- (void)submit:(MboxIsoSlot *)slot {
    enum { framesPerTransfer=8, totalPackets=2600 };
    unsigned kind=slot.kind;
    if(_stopping || gStop || (!_bridge && _next[kind]>=totalPackets))return;
    slot.packet=_next[kind];_next[kind]+=framesPerTransfer;
    memset(slot.storage.mutableBytes,0,slot.storage.length);
    memset(slot.data.mutableBytes,0,slot.data.length);
    IOUSBHostIsochronousTransaction *t=slot.storage.mutableBytes;
    const NSUInteger capacity=kind==1?3:MBOX_PACKET_CAPACITY;
    for(NSUInteger i=0;i<framesPerTransfer;i++) {
        t[i].offset=(uint32_t)(i*capacity);t[i].requestCount=(uint32_t)capacity;
        if(kind==0){
            size_t frames=0;
            if(!mbox_next_packet(&_clock,&frames)){_failed=YES;_stopping=YES;return;}
            t[i].requestCount=(uint32_t)(frames*MBOX_BYTES_PER_FRAME);
            // Prime the feedback clock using silence for the first 200ms.
            if(_bridge){
                uint8_t *wire=(uint8_t *)slot.data.mutableBytes+t[i].offset;
                for(size_t j=0;j<frames;j++){
                    float l=0,r=0;BOOL valid=mbox_ring_read(_bridge->output,_outputSample+j,&l,&r,mbox_load(&_bridge->generation));
                    if(!valid && mbox_load(&_bridge->clients)) __atomic_fetch_add(&_bridge->output_missed,1,__ATOMIC_RELAXED);
                    if(valid)__atomic_fetch_add(&_bridge->output_valid,1,__ATOMIC_RELAXED);
                    if(l!=0 || r!=0)__atomic_fetch_add(&_bridge->output_nonzero,1,__ATOMIC_RELAXED);
                    mbox_pack_s24be(wire+j*6,(int32_t)lrint(fmax(-1,fmin(1,l))*8388607));
                    mbox_pack_s24be(wire+j*6+3,(int32_t)lrint(fmax(-1,fmin(1,r))*8388607));
                }
            } else if(slot.packet+i>=200 && _feedbackCount>0){
                mbox_test_tone((uint8_t *)slot.data.mutableBytes+t[i].offset,capacity,frames,_toneSample);
                _toneSample+=frames;
            }
            _outputSample+=frames;
            if(_bridge)mbox_store(&_bridge->output_consumed,_outputSample);
        }
    }
    NSError *error=nil;
    _outstanding++;
    BOOL ok=[slot.pipe enqueueIORequestWithData:slot.data transactionList:t transactionListCount:framesPerTransfer
        firstFrameNumber:_baseFrame+slot.packet options:IOUSBHostIsochronousTransferOptionsNone error:&error
        completionHandler:^(IOReturn status,IOUSBHostIsochronousTransaction *transactions){
            // Framework delivers callbacks on _queue, which also owns every state update.
            self->_outstanding--;
            const uint8_t *data=slot.data.bytes;
            if(status!=kIOReturnSuccess && !self->_stopping){
                checkpoint(@"duplex.transfer.error",@{@"kind":@(kind),@"status":@(status),@"packet":@(slot.packet)});
                self->_failed=YES;self->_stopping=YES;
            }
            for(NSUInteger i=0;i<framesPerTransfer;i++) {
                IOUSBHostIsochronousTransaction f=transactions[i];
                if(f.status!=kIOReturnSuccess || f.completeCount>capacity || f.offset>slot.data.length || f.completeCount>slot.data.length-f.offset){self->_bad[kind]++;continue;}
                self->_good[kind]++;self->_bytes[kind]+=f.completeCount;
                if(kind==1){
                    if(mbox_accept_feedback(&self->_clock,data+f.offset,f.completeCount))self->_feedbackCount++;
                } else if(kind==2 && f.completeCount%6==0){
                    if(!self->_bridge)[self->_capture appendBytes:data+f.offset length:f.completeCount];
                    const uint64_t frameCount=f.completeCount/6;
                    if(self->_bridge){
                        for(uint64_t j=0;j<frameCount;j++){
                            const uint8_t *p=data+f.offset+j*6;
                            int32_t l=((int32_t)p[0]<<16)|((int32_t)p[1]<<8)|p[2];
                            int32_t r=((int32_t)p[3]<<16)|((int32_t)p[4]<<8)|p[5];
                            if(l&0x800000)l-=0x1000000;if(r&0x800000)r-=0x1000000;
                            mbox_ring_write(self->_bridge->input,self->_inputSample+j,l/8388608.f,r/8388608.f,mbox_load(&self->_bridge->generation));
                        }
                        uint64_t end=self->_inputSample+frameCount;
                        if(end>=self->_nextZero && frameCount){
                            double usbMillis=(double)(slot.packet+i+1)-(double)(end-self->_nextZero)/frameCount;
                            uint64_t host=self->_anchorHost+(uint64_t)(usbMillis*self->_ticksPerMillisecond);
                            __atomic_fetch_add(&self->_bridge->clock_seq,1,__ATOMIC_RELEASE);
                            mbox_store(&self->_bridge->clock_sample,self->_nextZero);mbox_store(&self->_bridge->clock_host,host);
                            __atomic_fetch_add(&self->_bridge->clock_seq,1,__ATOMIC_RELEASE);
                            self->_nextZero+=MBOX_CLOCK_PERIOD;
                        }
                        mbox_store(&self->_bridge->input_written,end);mbox_store(&self->_bridge->heartbeat,mach_absolute_time());
                        if(self->_feedbackCount>0 && end>1024)mbox_store(&self->_bridge->online,1);
                    }
                    self->_inputSample+=frameCount;
                    for(NSUInteger j=0;j<f.completeCount;j+=3){
                        const uint8_t *p=data+f.offset+j;int32_t v=((int32_t)p[0]<<16)|((int32_t)p[1]<<8)|p[2];
                        if(v&0x800000)v-=0x1000000;if(v<0)v=-v;if(v>self->_capturePeak)self->_capturePeak=v;
                    }
                }
            }
            if(self->_bad[kind]>3 || (slot.packet>=500 && self->_feedbackCount==0)){self->_failed=YES;self->_stopping=YES;}
            if(self->_bridge){
                mbox_store(&self->_bridge->playback_packets,self->_good[0]);mbox_store(&self->_bridge->capture_packets,self->_good[2]);
                mbox_store(&self->_bridge->feedback_valid,self->_feedbackCount);
                mbox_store(&self->_bridge->iso_errors,self->_bad[0]+self->_bad[1]+self->_bad[2]);
            }
            [self submit:slot];[self finishIfDrained];
        }];
    if(!ok){
        _outstanding--;_failed=YES;_stopping=YES;
        NSMutableDictionary *details=[failure(error) mutableCopy];details[@"kind"]=@(kind);
        details[@"scheduled_frame"]=@(_baseFrame+slot.packet);details[@"current_frame"]=@([_device frameNumberWithTime:NULL]);
        checkpoint(@"duplex.submit.error",details);
    }
}
- (NSDictionary *)run {
    NSError *error=nil;
    // Eight 8ms transfers per endpoint tolerate dispatch delays under desktop load.
    // CoreAudio's 4096-frame safety offset exceeds this 64ms queued output horizon.
    for(unsigned kind=0;kind<3;kind++)for(unsigned i=0;i<(_bridge?8u:4u);i++){
        MboxIsoSlot *s=[MboxIsoSlot new];s.kind=kind;s.pipe=_pipes[kind];
        s.data=[_device ioDataWithCapacity:8*(kind==1?3:MBOX_PACKET_CAPACITY) error:&error];
        s.storage=[_device dataWithCapacity:8*sizeof(IOUSBHostIsochronousTransaction)
            options:IOUSBHostObjectDataOptionsKernelUserShared error:&error];
        if(!s.data || !s.storage)return @{@"success":@NO,@"allocation_error":failure(error)};
        [_slots addObject:s];
    }
    checkpoint(@"duplex.start",_bridge?@{@"mode":@"coreaudio",@"continuous":@YES}:@{@"mode":@"tone",@"duration_ms":@2600,@"tone_hz":@480,@"tone_peak_dbfs":@(-42),@"tone_seconds":@2});
    dispatch_sync(_queue,^{
        IOUSBHostTime time=0;uint64_t lead=self->_bridge?96:48;
        self->_baseFrame=[self->_device frameNumberWithTime:&time]+lead;
        mach_timebase_info_data_t tb;mach_timebase_info(&tb);self->_ticksPerMillisecond=1e6*tb.denom/tb.numer;
        self->_anchorHost=time+(uint64_t)(lead*self->_ticksPerMillisecond);self->_nextZero=MBOX_CLOCK_PERIOD;
        if(self->_bridge){
            mbox_store(&self->_bridge->online,0);mbox_store(&self->_bridge->generation,mach_absolute_time());
            mbox_store(&self->_bridge->clock_sample,0);mbox_store(&self->_bridge->clock_host,self->_anchorHost);
            mbox_store(&self->_bridge->clients,0);
        }
        for(unsigned kind=1;kind<=3;kind++)for(MboxIsoSlot *s in self->_slots)if(s.kind==kind%3)[self submit:s];
        [self finishIfDrained];
    });
    BOOL completed=NO;
    if(_bridge){
        while(!gStop){
            if(dispatch_semaphore_wait(_done,dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC))==0){completed=YES;break;}
        }
        mbox_store(&_bridge->online,0);
    } else completed=dispatch_semaphore_wait(_done,dispatch_time(DISPATCH_TIME_NOW,6*NSEC_PER_SEC))==0;
    dispatch_sync(_queue,^{self->_stopping=YES;if(!completed && !gStop)self->_failed=YES;});
    // Abort from the calling thread so the callback queue can drain.
    for(IOUSBHostPipe *p in _pipes)[p abortWithOption:IOUSBHostAbortOptionSynchronous error:nil];
    dispatch_sync(_queue,^{});
    NSDictionary *result=@{@"success":@(!_failed && completed && _feedbackCount>0 && _good[0]>2000),
        @"playback_packets":@(_good[0]),@"feedback_packets":@(_good[1]),@"capture_packets":@(_good[2]),
        @"bad_packets":@[@(_bad[0]),@(_bad[1]),@(_bad[2])],@"bytes":@[@(_bytes[0]),@(_bytes[1]),@(_bytes[2])],
        @"valid_feedback":@(_feedbackCount),@"feedback_samples_per_ms":@((double)_clock.rate/16384),
        @"capture_peak_dbfs":@(_capturePeak?20*log10((double)_capturePeak/8388608):-144),
        @"captured_pcm_bytes":@(_capture.length),@"tone_sample_frames":@(_toneSample)};
    checkpoint(@"duplex.end",result);return result;
}
@end
