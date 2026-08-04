#!/bin/bash
# Q19: the free list is a std::deque<queue*> (map +0x6c, map_size +0x70,
# start +0x74..+0x80, finish +0x84..+0x90) and it is EMPTY with start.cur 16
# slots in -- 16 queues handed out, none returned. Read the worker thread
# (created at 0x459604) and the queue initialiser 0x4db6b8.
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "############ 0x4595c0 .. 0x45960c : worker thread entry + pool ctor head ############"
$OD -d --start-address=0x4595c0 --stop-address=0x459640 $G | sed -n '7,40p'

echo
echo "############ 0x4db6b8 : queue initialiser (learn where the fd lives) ############"
$OD -d --start-address=0x4db6b8 --stop-address=0x4db74c $G | sed -n '7,40p'

echo
echo "############ 0x459cd4 : the fd cache lookup ############"
$OD -d --start-address=0x459cd4 --stop-address=0x459d40 $G | sed -n '7,30p'
