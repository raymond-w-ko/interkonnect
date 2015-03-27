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
from wifi_scanner import *

METRIC = 9001

class State:
  DISCONNECTED = -1
  CONNECTING = 0
  CONNECTED = 1

class WifiConnection(threading.Thread):

  def __init__(self, parent, dev):
    threading.Thread.__init__(self)

    self.parent = parent
    self.dev = dev
    self.exiting = False
    self.suppressed = False
    self.event_queue = queue.Queue()
    self.print('entering DISCONNECTED state')
    self.state = State.DISCONNECTED
    self.temp_files = []

    self.wpa_supplicant = None
    self.wpa_supplicant_prev_data = ''

    self.dhcpcd = None
    self.dhcpcd_prev_data = ''

    self.enable_power_save()

    self.load_credentials()

    self.scanner_thread = WifiScanThread(self)
    self.scanner_thread.start()

    self.queue_watchdog_request()

    self.queue_listen_to_wpa_supplicant_request()
    self.queue_listen_to_dhcpcd_request()

  def print(self, msg):
    sys.stdout.write(str(datetime.datetime.now()))
    sys.stdout.write(' ')
    sys.stdout.write(self.dev)
    sys.stdout.write(': ')
    sys.stdout.write(msg)
    sys.stdout.write('\n')

  def enable_power_save(self):
    cmd = '%s dev %s set power_save on' % (IW, self.dev)
    self.print('attempting to turn on power save: %s' % (cmd))
    subprocess.call(cmd, shell=True)

  def kill_wpa_supplicant(self):
    try:
      if self.wpa_supplicant != None:
        self.wpa_supplicant.close(force=True)
        self.wpa_supplicant = None
    except:
      pass

  def kill_dhcpcd(self):
    try:
      if self.dhcpcd != None:
        self.dhcpcd.close(force=True)
        self.dhcpcd = None
    except:
      pass

  def cleanup(self):
    self.event_queue.put(['exiting', ''])
    self.scanner_thread.exiting = True
    self.exiting = True

    self.kill_dhcpcd()
    self.kill_wpa_supplicant()

    for file in self.temp_files:
      os.remove(file)
    self.temp_files.clear()

  def queue_watchdog_request(self):
    self.event_queue.put(['watchdog', ''])

  def watchdog(self, args):
    if self.exiting:
      return

    restart = False

    if self.suppressed:
      pass
    elif self.state == State.DISCONNECTED:
      pass
    elif self.state == State.CONNECTING:
      now = datetime.datetime.now()
      delta = now - self.connecting_start_time
      secs = delta.total_seconds()
      if secs > 30.0:
        restart = True
    elif self.state == State.CONNECTED:
      if self.dhcpcd == None or self.wpa_supplicant == None:
        restart = True
      elif not self.dhcpcd.isalive() or not self.wpa_supplicant.isalive():
        restart = True

    if restart:
      self.print('watchdog tripped, killing processes and resetting state')

      self.kill_dhcpcd()
      self.kill_wpa_supplicant()
      self.state = State.DISCONNECTED

    threading.Timer(5.0, self.queue_watchdog_request).start()

  def load_credentials(self):
    f = open(os.environ['HOME'] + '/.ssh/wificred')
    lines = f.read().split('\n')
    f.close()

    self.recognized_connections = {}
    for line in lines:
      if len(line) == 0:
        continue
      index = line.find(',')
      ssid = line[0:index]
      cred = line[index+1:]
      self.recognized_connections[ssid] = cred

  def connect(self, station):
    # TODO: need better heuristic in case there are two valid WiFi stations and
    # I am moving between them. So far, the last time this happened, I was in
    # college. Assume for now there is no reason to switch while you are connected
    if self.state >= State.CONNECTING:
      return

    self.print('connecting to wifi station "%s" (%s)' % (station['SSID'], station['bssid']))
    self.print('entering CONNECTING state')
    self.connecting_start_time = datetime.datetime.now()
    self.state = State.CONNECTING

    cred_path = self.prepare_credentials(station)
    self.start_wpa_supplicant(cred_path)

  def prepare_credentials(self, station):
    ssid = station['SSID']
    assert ssid in self.recognized_connections

    fd, path = tempfile.mkstemp(prefix='interkonnect.', dir='/tmp')
    self.temp_files.append(path)

    cred = self.recognized_connections[ssid]
    if len(cred) > 0:
      p = subprocess.Popen([WPA_PASSPHRASE, ssid], stdout = fd, stdin = subprocess.PIPE)
      p.stdin.write(bytes(cred, 'utf-8'))
      p.stdin.close()
      p.wait(timeout=5)
    else:
      os.write(fd, bytes("network={\n", 'utf-8'))
      os.write(fd, bytes("\tssid=\"%s\"\n" % (ssid), 'utf-8'))
      os.write(fd, bytes("proto=RSN\n", 'utf-8'))
      os.write(fd, bytes("key_mgmt=NONE\n", 'utf-8'))
      os.write(fd, bytes("}\n", 'utf-8'))
    os.close(fd)

    return path

  def start_wpa_supplicant(self, cred_path):
    self.kill_wpa_supplicant()

    cmd = '%s -i %s -c %s' % (WPA_SUPPLICANT, self.dev, cred_path)
    self.wpa_supplicant = pexpect.spawn(cmd, timeout=5)

  def queue_listen_to_wpa_supplicant_request(self):
    self.event_queue.put(['listen_to_wpa_supplicant', ''])

  def on_listen_to_wpa_supplicant(self, args):
    if self.wpa_supplicant is not None:
      try:
        data = self.wpa_supplicant.read_nonblocking(9001, 0)
        data = data.decode('utf-8')
        data = self.wpa_supplicant_prev_data + data
        tokens = data.split('\n')
        if not tokens[-1].endswith('\n'):
          self.wpa_supplicant_prev_data = tokens[-1]
          tokens.pop()
        else:
          self.wpa_supplicant_prev_data = ''
        for token in tokens:
          self.event_queue.put(['wpa_supplicant', token.strip()])
      except:
        pass
    threading.Timer(0.25, self.queue_listen_to_wpa_supplicant_request).start()

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

  def queue_listen_to_dhcpcd_request(self):
    self.event_queue.put(['listen_to_dhcpcd', ''])

  def on_listen_to_dhcpcd(self, args):
    if self.dhcpcd is not None:
      try:
        data = self.dhcpcd.read_nonblocking(9001, 0)
        data = data.decode('utf-8')
        data = self.dhcpcd_prev_data + data
        tokens = data.split('\n')
        if not tokens[-1].endswith('\n'):
          self.dhcpcd_prev_data = tokens[-1]
          tokens.pop()
        else:
          self.dhcpcd_prev_data = ''
        for token in tokens:
          self.event_queue.put(['dhcpcd', token.strip()])
      except:
        pass
    threading.Timer(0.25, self.queue_listen_to_dhcpcd_request).start()

  def on_wifi_stations(self, args):
    stations = args

    # since the list should already be sorted by signal strength, the first
    # recognized one should be the best
    best_station = None
    for station in stations:
      if 'SSID' not in station:
        continue
      ssid = station['SSID']
      if ssid in self.recognized_connections:
        best_station = station
        break

    if best_station == None:
      return
    self.connect(best_station)

  def on_wpa_supplicant(self, args):
    m = re.match(self.dev + ': (.+)', args)
    if m == None:
      return
    msg = m.group(1)
    self.print(msg)
    if msg.startswith('CTRL-EVENT-CONNECTED'):
      self.parent.flush_device_ip_addr(self.dev)
      self.print('wpa_supplicant reports successful connection, starting dhcpcd')
      self.start_dhcpcd()
    elif msg.startswith('CTRL-EVENT-DISCONNECTED'):
      self.print('wpa_supplicant reports disconnection, killing dhcpcd and wpa_supplicant')

      self.kill_dhcpcd()
      self.kill_wpa_supplicant()

      self.print('entering DISCONNECTED state')
      self.state = State.DISCONNECTED

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

  def suppress(self, args):
    self.suppressed = True
    self.kill_dhcpcd()
    self.kill_wpa_supplicant()
    self.parent.flush_device_ip_addr(self.dev)
    self.print('entering DISCONNECTED state')
    self.state = State.DISCONNECTED

  def unsuppress(self, args):
    self.suppressed = False

  def run(self):
    dispatcher = {}
    dispatcher['wifi_stations'] = self.on_wifi_stations
    dispatcher['watchdog'] = self.watchdog
    dispatcher['wpa_supplicant'] = self.on_wpa_supplicant
    dispatcher['listen_to_wpa_supplicant'] = self.on_listen_to_wpa_supplicant
    dispatcher['dhcpcd'] = self.on_dhcpcd
    dispatcher['listen_to_dhcpcd'] = self.on_listen_to_dhcpcd
    dispatcher['suppress'] = self.suppress
    dispatcher['unsuppress'] = self.unsuppress

    while True:
      event = self.event_queue.get()
      event_type = event[0]
      args = event[1]

      if event_type == 'exiting':
        break

      if event_type in dispatcher:
        dispatcher[event_type](args)
