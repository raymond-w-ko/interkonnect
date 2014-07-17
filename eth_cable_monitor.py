import threading
import subprocess
import re
import time

from constants import *

class EthernetCableMonitor(threading.Thread):
  def __init__(self, dev, queue):
    threading.Thread.__init__(self)
    self.dev = dev
    self.event_queue = queue
    self.last_state = -1

  def run(self):
    path = '/sys/class/net/' + self.dev + '/carrier'
    m = {0 : 'down', 1 : 'up'}

    while True:
      f = open(path, 'r')
      state = int(f.read().strip())
      f.close()

      if state != self.last_state:
        self.last_state = state
        self.event_queue.put(['cable_state_change', self.dev, m[state]])

      time.sleep(CABLE_POLL_INTERVALL)
