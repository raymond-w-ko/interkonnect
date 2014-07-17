import threading
import subprocess
import re
import time

from constants import *

class WifiScanThread(threading.Thread):
  def __init__(self, dev, queue):
    threading.Thread.__init__(self)
    self.dev = dev
    self.event_queue = queue

  def run(self):
    cmd = '%s dev %s scan' % (IW, self.dev)

    while True:
      output = subprocess.check_output(cmd, shell=True).decode('utf-8')
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

      self.event_queue.put(['wifi_stations', self.dev, stations])

      time.sleep(WIFI_SCAN_INTERVAL)
