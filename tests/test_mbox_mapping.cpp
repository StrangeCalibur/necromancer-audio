// SPDX-License-Identifier: MIT
#include "mbox_mapping.hpp"
#include <cassert>
#include <thread>
#include <vector>
#include <cstdio>
struct Value {unsigned number;};
static unsigned freed;
static void release(Value *v,size_t size){assert(size==sizeof(Value));delete v;freed++;}
int main() {
    MboxMapping<Value> slot(release);
    slot.publish(new Value{17},sizeof(Value));
    {
        auto held=slot.read();assert(held.get()->number==17);
        slot.publish(nullptr,0);slot.collect();
        assert(freed==0 && slot.retiredCount()==1 && !slot.canPublish());
        assert(held.get()->number==17);
    }
    assert(slot.canPublish() && freed==1);
    std::atomic<bool> done{false};
    std::vector<std::thread> readers;
    for(unsigned i=0;i<4;i++)readers.emplace_back([&]{while(!done.load()){
        auto read=slot.read();if(read.get())assert(read.get()->number==0xfeed);
    }});
    // Repeated reconnects exceed the old eight-mapping lifetime cap; no reader
    // can observe freed storage, and one retired mapping bounds reclamation.
    for(unsigned i=0;i<10000;i++){
        while(!slot.canPublish())std::this_thread::yield();
        slot.publish(new Value{0xfeed},sizeof(Value));
        slot.publish(nullptr,0);assert(slot.retiredCount()<=1);
    }
    done.store(true);for(auto& thread:readers)thread.join();
    slot.collect();assert(freed==10001 && slot.retiredCount()==0);
    puts("PASS: concurrent readers survive 10000 reconnects; all mappings reclaimed");
}
