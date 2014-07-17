#!/usr/bin/env python3

import os
import sys
import subprocess
import re
import threading
import time
import queue

from constants import *
from eth_cable_monitor import *
from wifi_scanner import *

class InterKonnect:

  def __init__(self):
    self.eth_dev = None
    self.wifi_dev = None

    self.event_queue = queue.Queue()

  def discover_devices(self):
    print('discovering interfaces')

    cmd = '%s link list' % (IP)
    output = subprocess.check_output(cmd, shell=True).decode('utf-8')
    lines = output.split('\n')
    for i in range(0, len(lines), 2):
      line = lines[i]
      if len(line) == 0:
        continue
      m = re.match(r'\d+:\s(.+): <', lines[i])
      dev = m.group(1)

      if dev.startswith('enp'):
        if self.eth_dev != None:
          assert False, 'multiple ethernet devices detected, this program will not work!'
        self.eth_dev = dev
      elif dev.startswith('wlp'):
        if self.wifi_dev != None:
          assert False, 'multiple wireless devices detected, this program will not work!'
        self.wifi_dev = dev

    if self.eth_dev == None:
      assert False, 'failed to find ethernet device'
    if self.wifi_dev == None:
      assert False, 'failed to find wireless device'

    print('using ethernet device: ' + self.eth_dev)
    print('using wireless device: ' + self.wifi_dev)

  def bring_device_up(self, dev):
    cmd = '%s link set %s up' % (IP, dev)
    print('bringing device up (%s)' % (cmd))
    subprocess.check_call(cmd, shell=True)

  def run(self):
    self.discover_devices()
    self.bring_device_up(self.eth_dev)
    self.bring_device_up(self.wifi_dev)

    self.scan_thread = WifiScanThread(self.wifi_dev, self.event_queue)
    self.scan_thread.start()

    self.cable_mon_thread = EthernetCableMonitor(self.eth_dev, self.event_queue)
    self.cable_mon_thread.start()

    while True:
      event = self.event_queue.get()
      type = event[0]
      dev = event[1]
      args = event[2]
      print('EVENT: ' + type)

      if type == 'wifi_stations':
        stations = args
        print('best station is: ' + stations[0]['SSID'])
      elif type == 'cable_state_change':
        print('cable is now: ' + args)
        pass
      else:
        pass

if __name__ == '__main__':
  if os.geteuid() != 0:
    print('interkonnect must be run as root!')
    sys.exit(1)

  if not os.path.isfile(IP):
    print(IP + ' does not exist!')
    sys.exit(2)
  if not os.path.isfile(IW):
    print(IW + ' does not exist!')
    sys.exit(2)

  interkonnect = InterKonnect()
  interkonnect.run()
