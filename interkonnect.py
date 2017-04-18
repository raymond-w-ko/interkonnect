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
from wifi_connection import *
from ethernet_connection import *

class InterKonnect:
  def __init__(self):
    self.eth_dev = None
    self.wifi_dev = None

    self.ethernet_connection = None
    self.wifi_connection = None

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

  def bring_device_down(self, dev):
    cmd = '%s link set %s down' % (IP, dev)
    print('bringing device down (%s)' % (cmd))
    subprocess.check_call(cmd, shell=True)

  def flush_device_ip_addr(self, dev):
    cmd = '%s addr flush %s' % (IP, dev)
    print('flushing IP addr of device (%s)' % (cmd))
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
      if self.ethernet_connection != None:
        self.ethernet_connection.cleanup()

      self.flush_device_ip_addr(self.eth_dev)
      self.bring_device_down(self.eth_dev)

      self.flush_device_ip_addr(self.wifi_dev)
      self.bring_device_down(self.wifi_dev)

      import hanging_threads
      sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)

  def suppress_wifi(self):
    print('suppressing WiFi')
    self.wifi_connection.event_queue.put(['suppress', ''])

  def unsuppress_wifi(self):
    print('unsuppressing WiFi')
    self.wifi_connection.event_queue.put(['unsuppress', ''])

  def run(self):
    self.install_ctrl_c_handler()

    self.discover_devices()
    self.bring_device_up(self.eth_dev)
    self.bring_device_up(self.wifi_dev)

    self.wifi_connection = WifiConnection(self, self.wifi_dev)
    self.wifi_connection.start()

    self.ethernet_connection = EthernetConnection(self, self.eth_dev)
    self.ethernet_connection.start()

    while True:
      event = self.event_queue.get()
      type = event[0]
      args = event[1]

      if type == 'exiting':
        break

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
