#!/usr/bin/env python
# Copyright(C) 2012 thomasv@gitorious

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see
# <http://www.gnu.org/licenses/agpl.html>.

import argparse
import ConfigParser
import logging
import socket
import sys
import time
import threading
import traceback

import json
import os

import utils
from backends.bitcoind import storage

logging.basicConfig()

if sys.maxsize <= 2**32:
    print "Warning: it looks like you are using a 32bit system. You may experience crashes caused by mmap"


def attempt_read_config(config, filename):
    try:
        with open(filename, 'r') as f:
            config.readfp(f)
    except IOError:
        pass


def setup_network_params(config):
    utils.PUBKEY_ADDRESS = config.getint('network', 'pubkey_address')
    utils.SCRIPT_ADDRESS = config.getint('network', 'script_address')
    storage.GENESIS_HASH = config.get('network', 'genesis_hash')

def create_config(filename=None):
    config = ConfigParser.ConfigParser()
    # set some defaults, which will be overwritten by the config file
    config.add_section('server')
    config.set('server', 'banner', 'Welcome to Electrum!')
    config.set('server', 'host', 'localhost')
    config.set('server', 'electrum_rpc_port', '8000')
    config.set('server', 'report_host', '')
    config.set('server', 'stratum_tcp_port', '50001')
    config.set('server', 'stratum_http_port', '8081')
    config.set('server', 'stratum_tcp_ssl_port', '50002')
    config.set('server', 'stratum_http_ssl_port', '8082')
    config.set('server', 'report_stratum_tcp_port', '')
    config.set('server', 'report_stratum_http_port', '')
    config.set('server', 'report_stratum_tcp_ssl_port', '')
    config.set('server', 'report_stratum_http_ssl_port', '')
    config.set('server', 'ssl_certfile', '')
    config.set('server', 'ssl_keyfile', '')
    config.set('server', 'password', '')
    config.set('server', 'irc', 'no')
    config.set('server', 'irc_nick', '')
    config.set('server', 'coin', '')
    config.set('server', 'datadir', '')

    # use leveldb as default
    config.set('server', 'backend', 'leveldb')
    config.add_section('leveldb')
    config.set('leveldb', 'path_fulltree', '/dev/shm/electrum_db')
    config.set('leveldb', 'pruning_limit', '100')

    # set network parameters
    config.add_section('network')
    config.set('network', 'pubkey_address', '0')
    config.set('network', 'script_address', '5')
    config.set('network', 'genesis_hash', '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f')

    # try to find the config file in the default paths
    if not filename:
        for path in ('/etc/', ''):
            filename = path + 'electrum.conf'
            if os.path.isfile(filename):
                break

    if not os.path.isfile(filename):
        print 'could not find electrum configuration file "%s"' % filename
        sys.exit(1)

    attempt_read_config(config, filename)

    try:
        with open('/etc/electrum.banner', 'r') as f:
            config.set('server', 'banner', f.read())
    except IOError:
        pass

    return config


def run_rpc_command(params, electrum_rpc_port):
    cmd = params[0]
    import xmlrpclib
    server = xmlrpclib.ServerProxy('http://localhost:%d' % electrum_rpc_port)
    func = getattr(server, cmd)
    r = func(*params[1:])

    if cmd == 'info':
        now = time.time()
        print 'type           address         sub  version  time'
        for item in r:
            print '%4s   %21s   %3s  %7s  %.2f' % (item.get('name'),
                                                   item.get('address'),
                                                   item.get('subscriptions'),
                                                   item.get('version'),
                                                   (now - item.get('time')),
                                                   )
    else:
        print r


def cmd_info():
    return map(lambda s: {"time": s.time,
                          "name": s.name,
                          "address": s.address,
                          "version": s.version,
                          "subscriptions": len(s.subscriptions)},
               dispatcher.request_dispatcher.get_sessions())

def cmd_debug(s):
    if s:
        from guppy import hpy
        h = hpy()
        bp = dispatcher.request_dispatcher.processors['blockchain']
        try:
            result = str(eval(s))
        except:
            result = "error"
        return result


def get_port(config, name):
    try:
        return config.getint('server', name)
    except:
        return None

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--conf', metavar='path', default=None, help='specify a configuration file')
    parser.add_argument('command', nargs='*', default=[], help='send a command to the server')
    args = parser.parse_args()

    config = create_config(args.conf)
    password = config.get('server', 'password')
    host = config.get('server', 'host')
    electrum_rpc_port = get_port(config, 'electrum_rpc_port')
    stratum_tcp_port = get_port(config, 'stratum_tcp_port')
    stratum_http_port = get_port(config, 'stratum_http_port')
    stratum_tcp_ssl_port = get_port(config, 'stratum_tcp_ssl_port')
    stratum_http_ssl_port = get_port(config, 'stratum_http_ssl_port')
    ssl_certfile = config.get('server', 'ssl_certfile')
    ssl_keyfile = config.get('server', 'ssl_keyfile')

    setup_network_params(config)

    if stratum_tcp_ssl_port or stratum_http_ssl_port:
        assert ssl_certfile and ssl_keyfile

    if len(args.command) >= 1:
        try:
            run_rpc_command(args.command, electrum_rpc_port)
        except socket.error:
            print "server not running"
            sys.exit(1)
        sys.exit(0)

    try:
        run_rpc_command(['getpid'], electrum_rpc_port)
        is_running = True
    except socket.error:
        is_running = False

    if is_running:
        print "server already running"
        sys.exit(1)


    from processor import Dispatcher, print_log
    from backends.irc import ServerProcessor
    from transports.stratum_tcp import TcpServer
    from transports.stratum_http import HttpServer

    backend_name = config.get('server', 'backend')
    if backend_name == 'libbitcoin':
        from backends.libbitcoin import BlockchainProcessor
    elif backend_name == 'leveldb':
        from backends.bitcoind import BlockchainProcessor
    else:
        print "Unknown backend '%s' specified\n" % backend_name
        sys.exit(1)

    print "\n\n\n\n\n"
    print_log("Starting Electrum server on", host)

    # Create hub
    dispatcher = Dispatcher(config)
    shared = dispatcher.shared

    # handle termination signals
    import signal
    def handler(signum = None, frame = None):
        print_log('Signal handler called with signal', signum)
        shared.stop()
    for sig in [signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT]:
        signal.signal(sig, handler)


    # Create and register processors
    chain_proc = BlockchainProcessor(config, shared)
    dispatcher.register('blockchain', chain_proc)

    server_proc = ServerProcessor(config)
    dispatcher.register('server', server_proc)

    transports = []
    # Create various transports we need
    if stratum_tcp_port:
        tcp_server = TcpServer(dispatcher, host, stratum_tcp_port, False, None, None)
        transports.append(tcp_server)

    if stratum_tcp_ssl_port:
        tcp_server = TcpServer(dispatcher, host, stratum_tcp_ssl_port, True, ssl_certfile, ssl_keyfile)
        transports.append(tcp_server)

    if stratum_http_port:
        http_server = HttpServer(dispatcher, host, stratum_http_port, False, None, None)
        transports.append(http_server)

    if stratum_http_ssl_port:
        http_server = HttpServer(dispatcher, host, stratum_http_ssl_port, True, ssl_certfile, ssl_keyfile)
        transports.append(http_server)

    for server in transports:
        server.start()

    

    from SimpleXMLRPCServer import SimpleXMLRPCServer
    server = SimpleXMLRPCServer(('localhost', electrum_rpc_port), allow_none=True, logRequests=False)
    server.register_function(lambda: os.getpid(), 'getpid')
    server.register_function(shared.stop, 'stop')
    server.register_function(cmd_info, 'info')
    server.register_function(cmd_debug, 'debug')
    server.socket.settimeout(1)
 
    while not shared.stopped():
        try:
            server.handle_request()
        except socket.timeout:
            continue
        except:
            shared.stop()

    server_proc.join()
    chain_proc.join()
    print_log("Electrum Server stopped")
