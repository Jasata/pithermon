#! /usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Raspberry Pi temperature and thermal throttling monitor/logger
#
# pithermon.py - Jani Tammi <jasata@utu.fi>
#   0.1     2018.08.29  Initial version.
#   0.2     2018.08.30  Added CSV export.
#   0.3     2018.08.31  CSV dialect support.
#   0.4     2018.08.31  Throttling information added.
#   0.5     2018.09.01  Added core voltage information.
#   0.5.5   2018.09.15  Added alarm commandline option.
#
# Python csv module is unable to deal with value formatting issues.
# In this case, it means that if a CSV conforming to Finnish locale is needed,
# the decimal separator in float values must be manually replaced ("." to ",").
# This is implemented into Data class, which needs to be given the correct
# CSV dialect on creation.
#
# Raspberry Pi throttling information is retrieved via firmware tool 'vcgencmd'
# and can report three conditions:
#
#   - under-voltage (voltage drops below 4.63V)
#   - arm frequency capped (temp > 80'C)
#   - over-temperature (temp > 85'C.)
#
# > vcgencmd get_throttled
# throttled=0x70000
#
# The 32-bit word is read as follows (bit index):
# https://github.com/raspberrypi/documentation/blob/JamesH65-patch-vcgencmd/raspbian/applications/vcgencmd.md
# (Edit 16.10.2018 by JamesH65)
#
# bit   11110000000000000010
#  0    ||||            ||||_ Under Voltage (right now)
#  1    ||||            |||_ ARM frequency Capped (right now)
#  2    ||||            ||_ Currently Throttled
#  3    ||||            |_ Soft Temp limit reached (in effect now)
# 16    ||||_ Under Voltage has occured since last reboot
# 17    |||_ ARM frequency capping has occured since last reboot
# 18    ||_ Throttling has occurred since last reboot
# 19    |_ Soft Temp limit has occurred
#
# NOTE: Soft Temp limit is specific for Raspberry Pi 3 B+ model only (in 2018).
#       None of the earlier models have this soft limit.
#
# WHAT IS THE DIFFERENCE BETWEEN THROTTLING, ARM FREQ CAPPING AND SOFT LIMIT?
#
#       TBA
#DISCREPANCY!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# bit-index
#        0: under-voltage                           & 0x0000 0001
#        1: arm frequency capped                    & 0x0000 0002
#        2: currently throttled                     & 0x0000 0004
#       16: under-voltage has occurred              & 0x0001 0000
#       17: arm frequency capped has occurred       & 0x0002 0000
#       18: throttling has occurred                 & 0x0004 0000
#
# Sample load (requires sysbench)
#
# sysbench --test=cpu --cpu-max-prime=20000 --num-threads=4 run
#
__version__ = "0.5.5"
__author__  = "Jani Tammi <jasata@utu.fi>"
VERSION = __version__
HEADER  = """
=============================================================================
University of Turku, Department of Future Technologies
ForeSail-1 / Raspberry Pi temperature and thermal throttling monitor
Version {}, 2018 {}
""".format(__version__, __author__)

import os
import re
import sys
import csv
import time
import argparse
import platform
import textwrap
import subprocess

__moduleName = os.path.basename(os.path.splitext(__file__)[0])
__fileName   = os.path.basename(__file__)

#
# Built in configuration defaults
#
class Config():
    # Either 'BASIC', 'STANDARD' or 'FULL'
    # Determined which columns are displayed/logged.
    # See documentation for details.
    Logging_Level = 'STANDARD'
    # Filename for the .CSV
    # If None, no file is written.
    CSV_File      = None
    # Localization/dialect for the .CSV
    # Commonly usable: 'finnish' or 'excel'
    CSV_Dialect   = 'finnish'
    # Data read interval in seconds
    # Values under 0.5 should be avoided
    Interval      = 1.0
    # Output console beeps when system is throttling
    # None = beeps are disabled
    # Otherwise the value must be a float that defines
    # the minimum time between beeps. (Does not need to be
    # defined as multiples of .Interval)
    Console_Alert = None

    # Commandline options are stored into this class
    # and this function can be used to show the configuration
    # values before and/or after value update.
    def show():
        print('Config.Logging_Level =', Config.Logging_Level)
        print('Config.CSV_File =',      Config.CSV_File)
        print('Config.CSV_Dialect =',   Config.CSV_Dialect)
        print('Config.Interval =',      Config.Interval)
        print('Config.Console_Alert =', Config.Console_Alert)

#
# Class for measurement data
#
class Data():
    time        = None
#    datetime    = ''
    cpu_temp    = 0.0
    cpu_load    = 0.0
    cpu_freq    = 0.0
    cpu_volts   = 0.0
    gpu_temp    = 0.0
    throttled   = 0x00
    decimal_separator = '.'
    def __init__(self, dialect):
        if dialect == 'finnish':
            self.decimal_separator = ','
    def read(self, now):
        self.time = lapsed_time(now)
        # self.datetime = time.strftime(
        #     "%Y-%m-%d %H:%M:%S",
        #     time.localtime(next_tick)
        # )
        self.cpu_temp  = cpu_temp()
        self.cpu_load  = cpu_load()
        self.cpu_freq  = cpu_freq()
        self.cpu_volts = cpu_volts()
        self.gpu_temp  = gpu_temp()
        self.throttled = get_throttled()
    def header(self):
        if Config.Logging_Level == 'BASIC':
            return  (
                        'Time',
                        'CPU Temperature',
                        'CPU MHz',
                        'ARM Frequency Capped',
                        'Throttled'
                    )
        elif Config.Logging_Level == 'STANDARD':
            return  (
                        'Time',
                        'CPU Temperature',
                        'CPU Load',
                        'CPU MHz',
                        'CPU Volts',
                        'Undervoltage',
                        'ARM Frequency Capped',
                        'Throttled'
                    )
        else: # FULL
            return  (
                        'Time',
                        'CPU Temperature',
                        'CPU Load',
                        'CPU MHz',
                        'CPU Volts',
                        'GPU Temperature',
                        'Undervoltage',
                        'ARM Frequency Capped',
                        'Throttled',
                        'Undervoltage has occured',
                        'ARM Frequencey Capping has occured',
                        'Throttling has occured'
                    )
    def __float2str(self, fval):
        if self.decimal_separator != '.':
            return str(round(fval, 1)).replace('.', self.decimal_separator)
        else:
            return str(round(fval, 1))
    def row(self):
        if Config.Logging_Level == 'BASIC':
            return  (
                        data.time,
                        self.__float2str(self.cpu_temp),
                        self.__float2str(self.cpu_freq),
                        1 if self.throttled & 0x02 else 0,
                        1 if self.throttled & 0x04 else 0
                    )
        elif Config.Logging_Level == 'STANDARD':
            return  (
                        data.time,
                        self.__float2str(self.cpu_temp),
                        self.__float2str(self.cpu_load),
                        self.__float2str(self.cpu_freq),
                        self.__float2str(self.cpu_volts),
                        1 if self.throttled & 0x01 else 0,
                        1 if self.throttled & 0x02 else 0,
                        1 if self.throttled & 0x04 else 0
                    )
        else: # FULL
            return  (
                    data.time,
                    self.__float2str(self.cpu_temp),
                    self.__float2str(self.cpu_load),
                    self.__float2str(self.cpu_freq),
                    self.__float2str(self.cpu_volts),
                    self.__float2str(self.gpu_temp),
                    1 if self.throttled & 0x01 else 0,
                    1 if self.throttled & 0x02 else 0,
                    1 if self.throttled & 0x04 else 0,
                    1 if self.throttled & 0x10000 else 0,
                    1 if self.throttled & 0x20000 else 0,
                    1 if self.throttled & 0x40000 else 0
                    )
    def throttled_string(self):
        """[UAT] string for stdout"""
        u = self.throttled & 0x00010001
        a = self.throttled & 0x00020002
        t = self.throttled & 0x00040004
        return  "[{}{}{}]" \
                .format(
                    "U" if u & 0x01 else "u" if u > 0x00 else " ",
                    "A" if a & 0x02 else "a" if a > 0x00 else " ",
                    "T" if t & 0x04 else "t" if t > 0x00 else " "
                )

#
# Register Finnish CSV dialect (only delimeter differs from defaults)
# Note: Python csv module is unable to deal with decimal separators.
#
csv.register_dialect('finnish', delimiter=';')


###############################################################################
# DEVELOPMENT FUNCTIONS (to be removed)
#convert string to hex
toHex = lambda x:"".join([hex(ord(c))[2:].zfill(2) for c in x])
#convert hex repr to string
#def toStr(s):
#    return s and chr(atoi(s[:2], base=16)) + toStr(s[2:]) or ''
###############################################################################

#
# Functions that you can copy into your own use
#
#@profile
def get_model():
    """Return the model of the board, as a string"""
    try:
        with open('/sys/firmware/devicetree/base/model', 'r') as f:
            return f.read().strip().strip('\0')
    except IOError as e:
        print('ERROR: %s' % e)
        sys.exit(3)

def get_revision():
    """Return revision number of the board, as a string"""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line[0:8] == 'Revision':
                    return line[line.find(':') + 1:].strip()
    except IOError as e:
        print('ERROR: %s' % e)
        sys.exit(3)

def get_serial():
    """Return serial number of the BCM chip as a string"""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line[0:6] == 'Serial':
                    return line[line.find(':') + 1:].strip()
    except IOError as e:
        print('ERROR: %s' % e)
        sys.exit(3)

def get_firmware():
    cmd = '/opt/vc/bin/vcgencmd'
    arg = 'version'
    return subprocess.check_output([cmd, arg]).decode('utf-8')


def cpu_times():
    """
    Returns a tuple of active and total CPU times. (active, total)
    """
    # cpu user nice system idle iowait irq softirq steal guest
    # 0   1    2    3      4    5      6   7       8     9
    active_indeces = [1, 2, 3, 7, 8]
    try:
        with open('/proc/stat', 'r') as procfile:
            cputimes  = procfile.readline()
            cputotal  = 0
            cpuactive = 0
            for index, element in enumerate(cputimes.split(' ')[2:]):
                value = int(element)
                cputotal += value
                if index in active_indeces:
                    cpuactive += value
            return (cpuactive, cputotal)
    except IOError as e:
        print('ERROR: %s' % e)
        sys.exit(3)

def cpu_load():
    try:
        prev = cpu_load.prev
    except AttributeError:
        prev = cpu_times()
    curr = cpu_times()
    try:
        load =  100.0 * \
                (float(curr[1] - prev[1]) - float(curr[0] - prev[0])) / \
                float(curr[1] - prev[1])
    except ZeroDivisionError:
        load = 0.0
    cpu_load.prev = curr
    return load

def cpu_freq():
    """ARM clock frequency MHz (float)"""
    cmd  = '/opt/vc/bin/vcgencmd'
    arg1 = 'measure_clock'
    arg2 = 'arm'
    string = subprocess.check_output([cmd, arg1, arg2]).decode('utf-8')
    return float(string[string.find('=') + 1:].strip()) / 1000000.0

def cpu_temp():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as tempfile:
            return float(tempfile.read()) / 1000
    except IOError as e:
        print('ERROR: %s' % e)
        sys.exit(3)

def gpu_temp():
    cmd = '/opt/vc/bin/vcgencmd'
    arg = 'measure_temp'
    string = subprocess.check_output([cmd, arg]).decode('utf-8')
    return float(string[string.find('=') + 1:].strip().rstrip('\'C'))

def get_throttled():
    """
    Returns throttled information
    0: under-voltage
    1: arm frequency capped
    2: currently throttled
    16: under-voltage has occurred
    17: arm frequency capped has occurred
    18: throttling has occurred
    """
    cmd = '/opt/vc/bin/vcgencmd'
    arg = 'get_throttled'
    string = subprocess.check_output([cmd, arg]).decode('utf-8')
    return int(string[string.find('=') + 1:].strip(), 16)

def cpu_volts():
    """ARM (and VideoCore) core voltage (float)"""
    cmd  = '/opt/vc/bin/vcgencmd'
    arg1 = 'measure_volts'
    arg2 = 'core'
    string = subprocess.check_output([cmd, arg1, arg2]).decode('utf-8')
    return float(string[string.find('=') + 1:].strip().rstrip('\'V'))

def lapsed_time(now):
    """HH:MM:SS string since 't' (for console output)"""
    try:
        (lapsed_time.start_time)
    except:
        lapsed_time.start_time = now
    lapsed = now - lapsed_time.start_time
    return time.strftime("%H:%M:%S", time.gmtime(lapsed))

def console_throttling_alert(data):
    """Issues a console boop every 'interval' seconds, if data.throttled is flagged"""
    if Config.Console_Alert is None:
        return
    try:
        (console_throttling_alert.last_beep)
    except:
        console_throttling_alert.last_beep = time.time()
    if (data.throttled & 0x07) == 0:
        return
    if (time.time() - console_throttling_alert.last_beep) > Config.Console_Alert:
        console_throttling_alert.last_beep = time.time()
        print('\a', end = "\r", flush = True)

def csv_write_header(csv):
    csv.writerow(
                    (
                        'Date',
                        time.strftime(
                            "%Y-%m-%d %H:%M:%S",
                            time.localtime(time.time())
                        )
                    )
    )
    # host, domain, ip
    csv.writerow(('Device', platform.node()))
    csv.writerow(('Hardware', get_model()))
    csv.writerow(('GPU Firmware', ' '.join(get_firmware().splitlines(False))))


###############################################################################
#
# Commandline execution
#
if __name__ == "__main__":

    # DEBUG
    #print("Built-in defaults:")
    #Config.show()

    #
    # Commandline arguments
    #
    ArgParser = argparse.ArgumentParser(
        description     = HEADER,
        formatter_class = argparse.RawTextHelpFormatter,
        epilog          = textwrap.dedent(
            """Throttling information
    Thermal throttling information is presented in and encoded format "[uat]".
    Each character can appear either as empty, lower case (has occured) or
    upper case (is happening now).
    
        U or u      under voltage (supply < 4.63 V)
        A or a      Arm frequency is or has been capped
        T or t      throttling is in effect or has happened during this uptime
        """
        )
    )
    ArgParser.add_argument(
        '-a',
        '--alert',
        help    = 'Ring console bell ("beep") when system is throttling',
        nargs   = '?',
        default = Config.Console_Alert,
        const   = Config.Interval,
        type    = float,
        metavar = "SECONDS"
    )
    ArgParser.add_argument(
        '-f',
        '--file',
        help    = "CSV file where data will be logged into",
        nargs   = '?',
        dest    = "csv_file",
        default = Config.CSV_File,
        type    = str,
        metavar = "FILE"
    )
    ArgParser.add_argument(
        '-d',
        '--dialect',
        help    = "CSV dialect " + str(csv.list_dialects()),
        choices = csv.list_dialects(),
        nargs   = '?',
        dest    = "csv_dialect",
        const   = "finnish",
        default = Config.CSV_Dialect,
        type    = str,
        metavar = "DIALECT"
    )
    ArgParser.add_argument(
        '-i',
        '--interval',
        help    = "Measurement interval in seconds",
        nargs   = '?',
        dest    = "interval",
        default = Config.Interval,
        type    = float,
        metavar = "SECONDS"
    )
    ArgParser.add_argument(
        '-l',
        '--log',
        help    = "Set logging level ['BASIC', 'STANDARD', 'FULL']",
        choices = ['BASIC', 'STANDARD', 'FULL'],
        nargs   = '?',
        dest    = "logging_level",
        const   = "STANDARD",
        default = Config.Logging_Level,
        type    = str.upper,
        metavar = "LEVEL"
    )
    args = ArgParser.parse_args()
    #
    # Update Config object
    #
    Config.CSV_File         = args.csv_file
    Config.CSV_Dialect      = args.csv_dialect
    Config.Logging_Level    = args.logging_level
    Config.Interval         = args.interval
    Config.Console_Alert    = args.alert

    # DEBUG
    print("PASSED HELP")
    #print("Run parameters:")
    #Config.show()

    #
    # Print program header
    #
    print(HEADER)
    print(
        "Running on Python ver.{} on {} {}" \
        .format(
            platform.python_version(),
            platform.system(),
            platform.release()
        )
    )
    print("{}, rev {}".format(get_model(), get_revision()))
    print("Serial: {}".format(get_serial()))
    print(
        "{} cores are available ({} cores in current OS)" \
        .format(
            os.cpu_count() or "Unknown number of",
            platform.architecture()[0]
        )
    )
    print(
        "GPU Firmware\n" + \
        '\t' + '\t'.join(get_firmware().splitlines(True))
    )
 

    if Config.Interval < 0.5:
        print("WARNING: You should not use interval less than 0.5 seconds!")

    data = Data(Config.CSV_Dialect)
    if Config.CSV_File is not None:
        csv_file = open(Config.CSV_File, 'w')
        csv = csv.writer(csv_file, dialect=Config.CSV_Dialect)
        csv_write_header(csv)
        csv.writerow(data.header())

    print("\nPress CTRL-C to terminate...")
    start_time = time.time()        # For console
    next_tick = start_time + 0.5    # 500 ms so that first sleep won't get negative number
    while True:
        try:
            sleep_duration = next_tick - time.time()
            # Avoid lag-induced negative sleep times
            if sleep_duration > 0:
                # Sleep until next_tick
                time.sleep(sleep_duration)
            # Measure and write CSV
            data.read(next_tick)
            console_throttling_alert(data)
            if Config.CSV_File is not None:
                csv.writerow(data.row())
            print(
                "[{}] CPU: {:>4.1f}ºC {:>1.2f}V {:>5.1f}% @ {:>6.1f} MHz, "\
                "GPU: {:>4.1f}ºC {}"
                .format(
                        lapsed_time(next_tick),
                        data.cpu_temp,
                        data.cpu_volts,
                        data.cpu_load,
                        data.cpu_freq,
                        data.gpu_temp,
                        data.throttled_string()
                ),
                end = "\r",
                flush = True
            )
            next_tick = next_tick + Config.Interval
        except KeyboardInterrupt:
            try:
                csv_file.close()
            except:
                pass
            print("")
            sys.exit()

# EOF