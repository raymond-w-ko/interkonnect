import threading
import subprocess
import re
import time
import queue
import os
import tempfile
import pexpect

from constants import *
from wifi_scanner import *

METRIC = 9001

class WifiConnection(threading.Thread):
  def __init__(self, dev):
    threading.Thread.__init__(self)

    self.dev = dev
    self.event_queue = queue.Queue()
    self.connected = False
    self.temp_files = []

    self.wpa_supplicant = None
    self.dhcpcd = None

    self.load_credentials()

    self.scanner_thread = WifiScanThread(self)
    self.scanner_thread.start()

  def cleanup(self):
    self.event_queue.put(['exiting', ''])
    self.scanner_thread.exiting = True

    if self.wpa_supplicant != None:
      self.wpa_supplicant.close(force=True)
      self.wpa_supplicant = None

    if self.dhcpcd != None:
      self.dhcpcd.close(force=True)
      self.dhcpcd = None

    for file in self.temp_files:
      os.remove(file)
    self.temp_files.clear()

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
    if self.connected:
      return

    print('connecting to wifi station "%s" (%s)' % (station['SSID'], station['bssid']))

    cred_path = self.prepare_credentials(station)
    self.start_wpa_supplicant(cred_path)

    self.connected = True

  def prepare_credentials(self, station):
    ssid = station['SSID']
    assert ssid in self.recognized_connections

    fd, path = tempfile.mkstemp(prefix='interkonnect', dir='/tmp')
    self.temp_files.append(path)

    cred = self.recognized_connections[ssid]
    if len(cred) > 0:
      p = subprocess.Popen([WPA_PASSPHRASE, ssid], stdout = fd, stdin = subprocess.PIPE)
      p.stdin.write(bytes(cred, 'utf-8'))
      p.stdin.close()
      p.wait(timeout=5)
      # TODO
      #fd.close()
    else:
      # TODO, manually write out an empty simple one
      assert False

    return path

  def start_wpa_supplicant(self, cred_path):
    if self.wpa_supplicant != None:
      self.wpa_supplicant.close(force=True)
      self.wpa_supplicant = None

    cmd = '%s -i %s -c %s' % (WPA_SUPPLICANT, self.dev, cred_path)
    self.wpa_supplicant = pexpect.spawn(cmd, timeout=99999999)
    self.wpa_supplicant_reader = threading.Thread(target=self.listen_to_wpa_supplicant)
    self.wpa_supplicant_reader.daemon = True
    self.wpa_supplicant_reader.start()

  def listen_to_wpa_supplicant(self):
    try:
      while True:
        for line in self.wpa_supplicant:
          line = line.decode('utf-8').strip()
          if len(line) == 0:
            continue
          self.event_queue.put(['wpa_supplicant', line])
    except Exception as e:
      print(e)
      print('wpa_supplicant listener thread died')

  def start_dhcpcd(self):
    if self.dhcpcd != None:
      self.dhcpcd.close(force=True)
      self.dhcpcd = None

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

    self.dhcpcd = pexpect.spawn(cmd, timeout=99999999)
    self.dhcpcd_reader = threading.Thread(target=self.listen_to_dhcpcd)
    self.dhcpcd_reader.daemon = True
    self.dhcpcd_reader.start()

  def listen_to_dhcpcd(self):
    try:
      while True:
        for line in self.dhcpcd:
          line = line.decode('utf-8').strip()
          if len(line) == 0:
            continue
          self.event_queue.put(['dhcpcd', line])
    except Exception as e:
      print(e)
      print('dhcpcd listener thread died')

  def on_wifi_stations(self, args):
    stations = args

    # since the list should already be sorted by signal strength, the first
    # recognized one should be the best
    best_station = None
    for station in stations:
      ssid = station['SSID']
      if self.recognized_connections[ssid]:
        best_station = station
        break

    if station == None:
      return
    self.connect(station)

  def on_wpa_supplicant(self, args):
    m = re.match(self.dev + ': (.+)', args)
    if m == None:
      return
    msg = m.group(1)
    if msg.startswith('CTRL-EVENT-CONNECTED'):
      self.start_dhcpcd()
    elif msg.startswith('CTRL-EVENT-DISCONNECTED'):
      pass


  def run(self):
    dispatcher = {}
    dispatcher['wifi_stations'] = self.on_wifi_stations
    dispatcher['wpa_supplicant'] = self.on_wpa_supplicant

    while True:
      event = self.event_queue.get()
      type = event[0]
      args = event[1]

      if type == 'exiting':
        break

      if event in dispatcher:
        dispatcher[event](args)

      elif type == 'dhcpcd':
        m = re.match(r'dhcpcd\[(\d+)\]: (.+): (.+)', args)
        if m == None:
          continue
        pid = m.group(1)
        dev = m.group(2)
        msg = m.group(3)

        m = re.match(r'acknowledged ([\d\.]+) from ([\d\.]+)', msg)
        if m != None:
          myip = m.group(1)
          gateway = m.group(2)
          print('gateway: ' + gateway)

        m = re.match(r'adding IP address ([\d\.]+)/(\d+)', msg)
        if m != None:
          myip = m.group(1)
          subnetmask = m.group(2)
          print('my ip address: ' + myip)

        m = re.match(r'adding route to ([\d\.]+)/(\d+)', msg)
        if m != None:
          routeip = m.group(1)
          subnetmask = m.group(2)
          print('adding route to: ' + routeip + '/' + subnetmask)

        m = re.match(r'adding default route via ([\d\.]+)', msg)
        if m != None:
          gateway = m.group(1)
          print('adding default route via: ' + gateway)
