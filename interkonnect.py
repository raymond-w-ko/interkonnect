#!/usr/bin/env python3

import os
import sys
import subprocess

def main():
  pass

if __name__ == '__main__':
  if os.geteuid() != 0:
    print('interkonnect must be run as root!')
    sys.exit(1)

  main()
