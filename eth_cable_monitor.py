import threading
import subprocess
import re
import time

from constants import *

class EthernetCableMonitor(threading.Thread):
  def __init__(self, parent):
    threading.Thread.__init__(self)

    self.parent = parent
    self.dev = parent.dev
    self.event_queue = parent.event_queue
    self.last_state = -1

    self.exiting = False

  def run(self):
    path = '/sys/class/net/' + self.dev + '/carrier'
    m = {0 : 'disconnected', 1 : 'connected'}

    while True:
      if self.exiting:
        break

      f = open(path, 'r')
      contents = f.read().strip()
      if len(contents) > 0:
        state = int(contents)

        if state != self.last_state:
          self.last_state = state
          self.event_queue.put(['cable_state_change', m[state]])

      f.close()

      time.sleep(CABLE_POLL_INTERVALL)
