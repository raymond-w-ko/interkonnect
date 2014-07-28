import threading
import subprocess
import re
import time
import queue
import os
import tempfile
import pexpect
import sys

from constants import *
from eth_cable_monitor import *

METRIC = 100

class State:
  DISCONNECTED = -1
  CONNECTING = 0
  CONNECTED = 1

class EthernetConnection(threading.Thread):
  def __init__(self, dev):
    threading.Thread.__init__(self)

    self.dev = dev
    self.event_queue = queue.Queue()

    self.print('entering DISCONNECTED state')
    self.state = State.DISCONNECTED

    self.dhcpcd = None
    self.dhcpcd_reader = None

    self.cable_mon_thread = EthernetCableMonitor(self)
    self.cable_mon_thread.start()

  def print(self, msg):
    sys.stdout.write(self.dev)
    sys.stdout.write(': ')
    sys.stdout.write(msg)
    sys.stdout.write('\n')

  def kill_dhcpcd(self):
    try:
      if self.dhcpcd != None:
        self.dhcpcd.close(force=True)
        self.dhcpcd = None
    except:
      pass

  def cleanup(self):
    self.event_queue.put(['exiting', ''])
    self.cable_mon_thread.exiting = True

  def on_cable_state_change(self, args):
    if args == 'disconnected':
      self.print('cable disconnected, killing dhcpcd')
      self.kill_dhcpcd()
    elif args == 'connected':
      self.print('cable connected, starting dhcpcd')
      self.print('entering CONNECTING state')
      self.state = State.CONNECTING
      self.start_dhcpcd()

  def start_dhcpcd(self):
    self.kill_dhcpcd()

    cmd = '%s '
    # manually manage route to allow VPN killswitch
    #cmd += '--nogateway '
    # we will manually control process
    cmd += '--nobackground '
    # wifi should always have low priority
    cmd += '--metric %s ' % (METRIC)
    # we already use pdnsd, so this is not necessary
    cmd += '--nohook resolv.conf '
    # speed hack, no ARP check
    cmd += '--noarp '
    # speed hack, no ARP check
    cmd += '--ipv4only '
    # debug
    cmd += '-d '
    cmd += '%s'
    cmd = cmd % (DHCPCD, self.dev)

    self.dhcpcd = pexpect.spawn(cmd, timeout=5)

    if self.dhcpcd_reader == None:
      self.dhcpcd_reader = threading.Thread(target=self.listen_to_dhcpcd)
      self.dhcpcd_reader.daemon = True
      self.dhcpcd_reader.start()

  def listen_to_dhcpcd(self):
    while True:
      try:
        line = self.dhcpcd.readline()
        line = line.decode('utf-8').strip()
        if len(line) > 0:
          self.event_queue.put(['dhcpcd', line])
      except:
        pass

  def on_dhcpcd(self, args):
    m = re.match(r'dhcpcd\[(\d+)\]: (.+): (.+)', args)
    if m == None:
      return
    pid = m.group(1)
    dev = m.group(2)
    msg = m.group(3)

    m = re.match(r'acknowledged ([\d\.]+) from ([\d\.]+)', msg)
    if m != None:
      myip = m.group(1)
      gateway = m.group(2)
      self.print('gateway: ' + gateway)

    m = re.match(r'adding IP address ([\d\.]+)/(\d+)', msg)
    if m != None:
      myip = m.group(1)
      subnetmask = m.group(2)
      self.print('my ip address: ' + myip)

    m = re.match(r'adding route to ([\d\.]+)/(\d+)', msg)
    if m != None:
      routeip = m.group(1)
      subnetmask = m.group(2)
      self.print('adding route to: ' + routeip + '/' + subnetmask)
      self.state = State.CONNECTED
      self.print('entering CONNECTED state')

    m = re.match(r'adding default route via ([\d\.]+)', msg)
    if m != None:
      gateway = m.group(1)
      self.print('adding default route via: ' + gateway)

  def run(self):
    dispatcher = {}
    dispatcher['cable_state_change'] = self.on_cable_state_change
    dispatcher['dhcpcd'] = self.on_dhcpcd

    while True:
      event = self.event_queue.get()
      event_type = event[0]
      args = event[1]

      if event_type == 'exiting':
        break

      if event_type in dispatcher:
        dispatcher[event_type](args)
