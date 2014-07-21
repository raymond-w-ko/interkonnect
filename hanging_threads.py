"""
copy this code and do

    import hanging_threads

If a thread is at the same place for SECONDS_FROZEN then the stacktrace is printed.

This script prints

--------------------    Thread 6628     --------------------
  File "hanging_threads.py", line 70, in <module>
        time.sleep(3) # TEST
--------------------    Thread 6628     --------------------
  File "hanging_threads.py", line 70, in <module>
        time.sleep(3) # TEST

"""
import sys
import threading
try:
    from threading import get_ident
except ImportError:
    from thread import get_ident
import linecache
import time

SECONDS_FROZEN = 10 # seconds
TESTS_PER_SECOND = 10

def frame2string(frame):
    # from module traceback
    lineno = frame.f_lineno # or f_lasti
    co = frame.f_code
    filename = co.co_filename
    name = co.co_name
    s = '  File "{}", line {}, in {}'.format(filename, lineno, name)
    line = linecache.getline(filename, lineno, frame.f_globals).lstrip()
    return s + '\n\t' + line

def thread2list(frame):
    l = []
    while frame:
        l.insert(0, frame2string(frame))
        frame = frame.f_back
    return l

def monitor():
    self = get_ident()
    old_threads = {}
    while 1:
        time.sleep(1. / TESTS_PER_SECOND)
        now = time.time()
        then = now - SECONDS_FROZEN
        frames = sys._current_frames()
        new_threads = {}
        for frame_id, frame in frames.items():
            new_threads[frame_id] = thread2list(frame)
        for thread_id, frame_list in new_threads.items():
            if thread_id == self: continue
            if thread_id not in old_threads or \
               frame_list != old_threads[thread_id][0]:
                new_threads[thread_id] = (frame_list, now)
            elif old_threads[thread_id][1] < then:
                print_frame_list(frame_list, frame_id)
            else:
                new_threads[thread_id] = old_threads[thread_id]
        old_threads = new_threads

def print_frame_list(frame_list, frame_id):
    sys.stderr.write('-' * 20 + 
                     'Thread {}'.format(frame_id).center(20) +
                     '-' * 20 +
                     '\n' + 
                     ''.join(frame_list))

def start_monitoring():
    '''After hanging SECONDS_FROZEN the stack trace of the deadlock is printed automatically.'''
    thread = threading.Thread(target = monitor)
    thread.daemon = True
    thread.start()
    return thread

monitoring_thread = start_monitoring()

if __name__ == '__main__':
    SECONDS_FROZEN = 1
    time.sleep(3) # TEST
