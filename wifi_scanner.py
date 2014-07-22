import threading
import subprocess
import re
import time
import wifi_connection

from constants import *

class WifiScanThread(threading.Thread):
  def __init__(self, parent):
    threading.Thread.__init__(self)

    self.parent = parent
    self.dev = parent.dev
    self.event_queue = parent.event_queue

    self.exiting = False

  def scan(self):
    cmd = '%s dev %s scan' % (IW, self.dev)
    output = subprocess.check_output(cmd, shell=True).decode('utf-8')
    if self.exiting:
      return
    lines = output.split('\n')

    stations = []

    station = None
    for line in lines:
      if len(line) == 0:
        continue;

      if line[0] != '\t':
        # new station
        station = {}
        stations.append(station)
        m = re.match(r'BSS (.+)\(on (.+)\)', line)
        station['bssid'] = m.group(1)
        station['dev'] = m.group(2)
      else:
        m = re.match(r'\t*(.+?):\s(.+)', line)
        if m == None:
          continue
        station[m.group(1)] = m.group(2)

    def getkey(a):
      return float(a['signal'][:-4])
    stations.sort(key=getkey)
    stations.reverse()

    self.event_queue.put(['wifi_stations', stations])

  def run(self):
    while True:
      if self.exiting:
        break
      if self.parent.state == wifi_connection.State.DISCONNECTED:
        self.scan()
      time.sleep(WIFI_SCAN_INTERVAL)
