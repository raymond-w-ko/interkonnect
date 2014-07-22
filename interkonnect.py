#!/usr/bin/env python3

import os
import sys
import subprocess
import re
import threading
import time
import queue
import signal

from constants import *
from eth_cable_monitor import *
from wifi_connection import *

class InterKonnect:
  def __init__(self):
    self.eth_dev = None
    self.wifi_dev = None

    self.wifi_connection = None

    # TODO: remove this
    self.event_queue = queue.Queue()

  def discover_devices(self):
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

    print('using ethernet device %s and wireless device %s' % (self.eth_dev, self.wifi_dev))

  def bring_device_up(self, dev):
    cmd = '%s link set %s up' % (IP, dev)
    print('bringing device up (%s)' % (cmd))
    subprocess.check_call(cmd, shell=True)

  def install_ctrl_c_handler(self):
    self.num_interrupts = 0

    def signal_handler(signal, frame):
      self.num_interrupts += 1
      if self.num_interrupts > 1:
        return

      self.event_queue.put(['exiting', ''])

      if self.wifi_connection != None:
        self.wifi_connection.cleanup()

      import hanging_threads
      sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

  def run(self):
    self.install_ctrl_c_handler()

    self.discover_devices()
    self.bring_device_up(self.eth_dev)
    self.bring_device_up(self.wifi_dev)

    self.wifi_connection = WifiConnection(self.wifi_dev)
    self.wifi_connection.start()

    #self.cable_mon_thread = EthernetCableMonitor(self.eth_dev, self.event_queue)
    #self.cable_mon_thread.start()

    while True:
      event = self.event_queue.get()
      type = event[0]
      args = event[1]

      if type == 'exiting':
        break
      elif type == 'cable_state_change':
        print('cable is now: ' + args)
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
