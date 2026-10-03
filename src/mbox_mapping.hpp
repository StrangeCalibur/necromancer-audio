// SPDX-License-Identifier: MIT
#pragma once
#include <atomic>
#include <cstddef>
#include <vector>

// One control-queue writer; any number of realtime readers. Readers do no
// allocation, locking or cleanup. Retired mappings are freed only after every
// pre-exchange reader has exited. Sequential consistency orders entry, pointer
// acquisition, exchange and the writer's quiescence check across all threads.
template<class T> class MboxMapping {
public:
    using Release = void (*)(T *, size_t);
    explicit MboxMapping(Release release):release_(release){}
    MboxMapping(const MboxMapping&)=delete;
    class Reader {
        MboxMapping& owner_;
        T *value_;
    public:
        explicit Reader(MboxMapping& owner):owner_(owner) {
            owner_.readers_.fetch_add(1);
            value_=owner_.current_.load();
        }
        ~Reader(){owner_.readers_.fetch_sub(1);}
        Reader(const Reader&)=delete;
        T *get() const{return value_;}
    };
    Reader read(){return Reader(*this);}
    // Control queue only. Call collect periodically, including while offline.
    T *get() const{return current_.load();}
    bool canPublish(){collect();return retired_.empty();}
    void publish(T *next, size_t size) {
        T *previous=current_.exchange(next);
        if(previous)retired_.push_back({previous,size_});
        size_=size;collect();
    }
    void collect() {
        if(readers_.load()!=0)return;
        for(auto item:retired_)release_(item.pointer,item.size);
        retired_.clear();
    }
    size_t retiredCount() const{return retired_.size();}
private:
    struct Entry{T *pointer;size_t size;};
    static_assert(std::atomic<T *>::is_always_lock_free);
    static_assert(std::atomic<unsigned>::is_always_lock_free);
    std::atomic<T *> current_{nullptr};
    std::atomic<unsigned> readers_{0};
    size_t size_=0;
    std::vector<Entry> retired_;
    Release release_;
};
