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

  def __init__(self, dev):
    threading.Thread.__init__(self)

    self.dev = dev
    self.exiting = False
    self.event_queue = queue.Queue()
    self.print('entering DISCONNECTED state')
    self.state = State.DISCONNECTED
    self.temp_files = []

    self.wpa_supplicant = None
    self.wpa_supplicant_reader = None

    self.dhcpcd = None
    self.dhcpcd_reader = None

    self.enable_power_save()

    self.load_credentials()

    self.scanner_thread = WifiScanThread(self)
    self.scanner_thread.start()

    self.watchdog()

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

    self.kill_wpa_supplicant()
    self.kill_dhcpcd()

    for file in self.temp_files:
      os.remove(file)
    self.temp_files.clear()

  def watchdog(self):
    if self.exiting:
      return

    restart = False

    if self.state == State.DISCONNECTED:
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

      self.kill_wpa_supplicant()
      self.kill_dhcpcd()
      self.state = State.DISCONNECTED

    t = threading.Timer(5.0, self.watchdog)
    t.start()

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

    if self.wpa_supplicant_reader == None:
      self.wpa_supplicant_reader = threading.Thread(target=self.listen_to_wpa_supplicant)
      self.wpa_supplicant_reader.daemon = True
      self.wpa_supplicant_reader.start()

  def listen_to_wpa_supplicant(self):
    while True:
      try:
        # avoid spin loop
        if self.wpa_supplicant == None or not self.wpa_supplicant.isalive():
          time.sleep(0.1)
          continue

        line = self.wpa_supplicant.readline()
        line = line.decode('utf-8').strip()
        if len(line) > 0:
          self.event_queue.put(['wpa_supplicant', line])
      except:
        pass

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
        # avoid spin loop
        if self.dhcpcd == None or not self.dhcpcd.isalive():
          time.sleep(0.1)
          continue

        line = self.dhcpcd.readline()
        line = line.decode('utf-8').strip()
        if len(line) > 0:
          self.event_queue.put(['dhcpcd', line])
      except:
        pass

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
      self.print('wpa_supplicant reports successful connection, starting dhcpcd')
      self.start_dhcpcd()
    elif msg.startswith('CTRL-EVENT-DISCONNECTED'):
      self.print('wpa_supplicant reports disconnection, killing dhcpcd and wpa_supplicant')

      self.kill_dhcpcd()
      self.kill_wpa_supplicant()

      self.print('entering DISCONNECTED state')
      self.state = State.DISCONNECTED

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
    dispatcher['wifi_stations'] = self.on_wifi_stations
    dispatcher['wpa_supplicant'] = self.on_wpa_supplicant
    dispatcher['dhcpcd'] = self.on_dhcpcd

    while True:
      event = self.event_queue.get()
      event_type = event[0]
      args = event[1]

      if event_type == 'exiting':
        break

      if event_type in dispatcher:
        dispatcher[event_type](args)
