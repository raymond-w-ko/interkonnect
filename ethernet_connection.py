import threading
import subprocess
import re
import time
import queue
import os
import tempfile
import pexpect
import sys
import datetime

from constants import *
from eth_cable_monitor import *

METRIC = 100

class State:
  DISCONNECTED = -1
  CONNECTING = 0
  CONNECTED = 1

class EthernetConnection(threading.Thread):
  def __init__(self, parent, dev):
    threading.Thread.__init__(self)

    self.parent = parent
    self.dev = dev
    self.event_queue = queue.Queue()

    self.print('entering DISCONNECTED state')
    self.state = State.DISCONNECTED

    self.dhcpcd = None
    self.prev_data = ''

    self.cable_mon_thread = EthernetCableMonitor(self)
    self.cable_mon_thread.start()

    self.queue_listen_to_dhcpcd_request()

  def print(self, msg):
    sys.stdout.write(str(datetime.datetime.now()))
    sys.stdout.write(' ')
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
    self.kill_dhcpcd()

  def on_cable_state_change(self, args):
    if args == 'disconnected':
      self.print('cable disconnected, killing dhcpcd')
      self.kill_dhcpcd()
      self.parent.flush_device_ip_addr(self.dev)
      self.parent.unsuppress_wifi()
    elif args == 'connected':
      self.print('cable connected, starting dhcpcd')
      self.print('entering CONNECTING state')
      self.state = State.CONNECTING
      self.parent.flush_device_ip_addr(self.dev)
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

  def on_dhcpcd(self, args):
    #m = re.match(r'dhcpcd\[(\d+)\]: (.+): (.+)', args)
    #if m == None:
      #return
    #pid = m.group(1)
    #dev = m.group(2)
    #msg = m.group(3)
    m = re.match(r'(.+?): (.+)', args)
    if m == None:
      return
    dev = m.group(1)
    msg = m.group(2)

    m = re.match(r'acknowledged ([\d\.]+) from ([\d\.]+)', msg)
    if m != None:
      myip = m.group(1)
      gateway = m.group(2)
      self.print('gateway: ' + gateway)
      return

    m = re.match(r'adding IP address ([\d\.]+)/(\d+)', msg)
    if m != None:
      myip = m.group(1)
      subnetmask = m.group(2)
      self.print('my ip address: ' + myip)
      return

    m = re.match(r'adding route to ([\d\.]+)/(\d+)', msg)
    if m != None:
      routeip = m.group(1)
      subnetmask = m.group(2)
      self.print('adding route to: ' + routeip + '/' + subnetmask)
      self.state = State.CONNECTED
      self.print('entering CONNECTED state')
      self.parent.suppress_wifi()
      return

    m = re.match(r'adding default route via ([\d\.]+)', msg)
    if m != None:
      gateway = m.group(1)
      self.print('adding default route via: ' + gateway)
      return

  def queue_listen_to_dhcpcd_request(self):
    self.event_queue.put(['listen_to_dhcpcd', ''])

  def on_listen_to_dhcpcd(self, args):
    if self.dhcpcd is not None:
      try:
        data = self.dhcpcd.read_nonblocking(9001, 0)
        data = data.decode('utf-8')
        data = self.prev_data + data
        tokens = data.split('\n')
        if not tokens[-1].endswith('\n'):
          self.prev_data = tokens[-1]
          tokens.pop()
        else:
          self.prev_data = ''
        for token in tokens:
          self.event_queue.put(['dhcpcd', token.strip()])
      except:
        pass
    threading.Timer(0.25, self.queue_listen_to_dhcpcd_request).start()

  def run(self):
    dispatcher = {}
    dispatcher['cable_state_change'] = self.on_cable_state_change
    dispatcher['dhcpcd'] = self.on_dhcpcd
    dispatcher['listen_to_dhcpcd'] = self.on_listen_to_dhcpcd

    while True:
      event = self.event_queue.get()
      event_type = event[0]
      args = event[1]

      if event_type == 'exiting':
        break

      if event_type in dispatcher:
        dispatcher[event_type](args)
