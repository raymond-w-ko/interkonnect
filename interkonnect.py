#!/usr/bin/env python3

import os
import sys
import subprocess
import re
import threading
import time

IP = '/usr/bin/ip'
IW = '/usr/bin/iw'

ETH_DEV = None
WIFI_DEV = None

WIFI_SCAN_INTERVAL = 5

def discover_devices():
  print('discovering interfaces')

  global ETH_DEV
  global WIFI_DEV

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
      if ETH_DEV != None:
        assert False, 'multiple ethernet devices detected, this program will not work!'
      ETH_DEV = dev
    elif dev.startswith('wlp'):
      if WIFI_DEV != None:
        assert False, 'multiple wireless devices detected, this program will not work!'
      WIFI_DEV = dev

  if ETH_DEV == None:
    assert False, 'failed to find ethernet device'
  if WIFI_DEV == None:
    assert False, 'failed to find wireless device'

  print('using ethernet device: ' + ETH_DEV)
  print('using wireless device: ' + WIFI_DEV)

def bring_device_up(dev):
  cmd = '%s link set %s up' % (IP, dev)
  print('bringing device up (%s)' % (cmd))
  subprocess.check_call(cmd, shell=True)

class WifiScanThread(threading.Thread):
  def __init__(self):
    threading.Thread.__init__(self)
    pass

  def run(self):
    cmd = '%s dev %s scan' % (IW, WIFI_DEV)

    while True:
      output = subprocess.check_output(cmd, shell=True).decode('utf-8')
      lines = output.split('\n')
      for line in lines:
        print(line)

      time.sleep(WIFI_SCAN_INTERVAL)
      
def main():
  discover_devices()
  bring_device_up(ETH_DEV)
  bring_device_up(WIFI_DEV)

  WifiScanThread().start()

  time.sleep(5000)

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

  main()
