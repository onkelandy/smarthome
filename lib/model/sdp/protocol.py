#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2020-      Sebastian Helms             Morg @ knx-user-forum
#########################################################################
#  This file aims to become part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  SDPProtocol and derived classes for SmartDevicePlugin class
#
#  SmartHomeNG is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHomeNG is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHomeNG. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

from __future__ import annotations

import ast
import json
import queue
import re
import sys
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from time import time
from typing import Any

from lib.model.sdp.globals import (
    CONN_NET_TCP_CLI, JSON_MOVE_KEYS, PLUGIN_ATTR_CB_ON_CONNECT,
    PLUGIN_ATTR_CB_ON_DISCONNECT, PLUGIN_ATTR_CONNECTION, PLUGIN_ATTR_NET_PORT,
    PLUGIN_ATTR_SEND_RETRIES, PLUGIN_ATTR_SEND_RETRY_CYCLE, PLUGIN_ATTR_SEND_TIMEOUT,
    PLUGIN_ATTR_PROTOCOL, PROTOCOL_TYPES, PROTO_NULL)
from lib.model.sdp.connection import SDPConnection


#############################################################################################################################################################################################################################################
#
# class SDPProtocol and subclasses
#
#############################################################################################################################################################################################################################################

class SDPProtocol(SDPConnection):
    """ SDPProtocol class to provide protocol support for SmartDevicePlugin

    This class implements a basic protocol layer to act as a standin between
    the plugin class and the SDPConnection-class. Its purpose is to enable
    establishing a control layer, so the connection only has to care for the
    'physical' connection and the device only needs to operate on commmand basis.

    This implementation can also be seen as a 'NULL' protocol, it only passes
    along everything.

    By overwriting this class, different protocols can be implemented independent
    of the device and the connection classes.
    """

    def __init__(self, data_received_callback: Callable | None, name: str | None = None, **kwargs):

        # init super, get logger
        super().__init__(data_received_callback, name, **kwargs)

        self.logger.debug(f'protocol initializing from {self.__class__.__name__} with arguments {kwargs}')

        # make sure we have a basic set of parameters
        self._params.update({PLUGIN_ATTR_CONNECTION: SDPConnection})
        self._params.update(kwargs)

        # check if some of the arguments are usable
        self._set_connection_params()

        # initialize connection
        conn_params = self._params.copy()
        conn_params.update({PLUGIN_ATTR_CB_ON_CONNECT: self.on_connect, PLUGIN_ATTR_CB_ON_DISCONNECT: self.on_disconnect})
        self._connection = self._params[PLUGIN_ATTR_CONNECTION](self.on_data_received, name=name, **conn_params)

        # tell someone about our actual class
        self.logger.debug(f'protocol initialized from {self.__class__.__name__}')

    def _open(self) -> bool:
        self.logger.debug(f'{self.__class__.__name__} _open called, opening protocol with params {self._params}')
        if not self._connection.connected():
            self._connection.open()

        self._is_connected = self._connection.connected()
        return self._is_connected

    def _close(self):
        self.logger.debug(f'{self.__class__.__name__} _close called, closing protocol')
        self._connection.close()
        self._is_connected = False

    def _send(self, data_dict: dict, **kwargs) -> Any:
        self.logger.debug(f'{self.__class__.__name__} _send called with {data_dict}')
        return self._connection.send(data_dict, **kwargs)

    def _get_connection(self, use_callbacks: bool = False, name: str | None = None):
        conn_params = self._params.copy()

        cb_data = self.on_data_received if use_callbacks else None
        cb_connect = self.on_connect if use_callbacks else None
        cb_disconnect = self.on_disconnect if use_callbacks else None
        conn_params.update({PLUGIN_ATTR_CB_ON_CONNECT: cb_connect, PLUGIN_ATTR_CB_ON_DISCONNECT: cb_disconnect})

        conn_cls = self._get_connection_class(**conn_params)
        self._connection = conn_cls(cb_data, name=name, **conn_params)

    @staticmethod
    def _get_protocol_class(
            protocol_cls: type[SDPProtocol] | None = None,
            protocol_classname: str | None = None,
            protocol_type: str | None = None,
            **params) -> type[SDPProtocol] | None:

        protocol_module = sys.modules.get('lib.model.sdp.protocol', '')
        if not protocol_module:
            raise RuntimeError('unable to get object handle of SDPProtocol module')

        # class not set
        if not protocol_cls:

            # do we have a class type from params?
            if PLUGIN_ATTR_PROTOCOL in params and type(params[PLUGIN_ATTR_PROTOCOL]) is type and issubclass(params[PLUGIN_ATTR_PROTOCOL], SDPConnection):

                # directly use given class
                protocol_cls = params[PLUGIN_ATTR_PROTOCOL]
                protocol_classname = protocol_cls.__name__  # type: ignore (previous assignment makes protocol_cls type SDPProtocol)

            else:
                # classname not known
                if not protocol_classname:

                    # do we have a protocol name
                    if PLUGIN_ATTR_PROTOCOL in params and isinstance(params[PLUGIN_ATTR_PROTOCOL], str):
                        if params[PLUGIN_ATTR_PROTOCOL] not in PROTOCOL_TYPES:
                            protocol_classname = params[PLUGIN_ATTR_PROTOCOL]
                            protocol_type = 'manual'

                    # wanted connection type not known
                    if not protocol_type:

                        if PLUGIN_ATTR_PROTOCOL in params and params[PLUGIN_ATTR_PROTOCOL] in PROTOCOL_TYPES:
                            protocol_type = params[PLUGIN_ATTR_PROTOCOL]
                        else:
                            protocol_type = PROTO_NULL

                    # got unknown protocol type
                    if protocol_type not in PROTOCOL_TYPES:
                        # self.logger.error(f'protocol "{protocol_type}" specified, but unknown and not class type or class name. Using default protocol')
                        # just set default
                        protocol_type = PROTO_NULL

                    # get classname from type
                    protocol_classname = 'SDPProtocol' + ''.join([tok.capitalize() for tok in protocol_type.split('_')])

                # get class from classname
                protocol_cls = getattr(protocol_module, protocol_classname, None)

        if not protocol_cls:
            raise RuntimeError(f'protocol {params[PLUGIN_ATTR_PROTOCOL]} specified, but not loadable.')

        return protocol_cls


class SDPProtocolJsonrpc(SDPProtocol):
    """ Protocol support for JSON-RPC 2.0

    This class implements a protocol to send JSONRPC 2.0  compatible messages
    As JSONRPC includes message-ids, replies can be associated to their respective
    queries and reply tracing and command repeat functions are implemented.

    Fragmented packets need to be collected and assembled;
    multiple received json packets neet to be split;
    processed packets will then be returned as received data.

    Data received is dispatched via callback, thus the send()-method does not
    return any response data.

    Callback syntax is:
        def connected_callback(by=None)
        def disconnected_callback(by=None)
        def data_received_callback(by, message, command=None)
    If callbacks are class members, they need the additional first parameter 'self'

    """
    def __init__(self, data_received_callback: Callable | None, name: str | None = None, **kwargs):

        # init super, get logger
        super().__init__(data_received_callback, name, **kwargs)

        # make sure we have a basic set of parameters for the TCP connection
        self._params.update({PLUGIN_ATTR_NET_PORT: 9090,
                             PLUGIN_ATTR_SEND_RETRIES: 3,
                             PLUGIN_ATTR_SEND_TIMEOUT: 5,
                             PLUGIN_ATTR_CONNECTION: CONN_NET_TCP_CLI,
                             JSON_MOVE_KEYS: []})
        self._params.update(kwargs)

        # check if some of the arguments are usable
        self._set_connection_params()

        # set class properties
        self._shutdown_active = False

        self._message_id = 0
        self._msgid_lock = Lock()
        self._send_queue = queue.Queue()
        self._stale_lock = Lock()

        self._receive_buffer = bytes()

        # self._message_archive[str message_id] = [time() sendtime, str method, str params or None, int repeat]
        self._message_archive = {}

        self._check_stale_cycle = float(self._params[PLUGIN_ATTR_SEND_TIMEOUT]) / 2
        self._next_stale_check = 0
        self._last_stale_check = 0

        # initialize connection
        self._get_connection(True, name=name)

        # tell someone about our actual class
        self.logger.debug(f'protocol initialized from {self.__class__.__name__}')

    def on_connect(self, by=None):
        self.logger.info(f'onconnect called by {by}, send queue contains {self._send_queue.qsize()} commands')
        super().on_connect(by)

    def on_disconnect(self, by=None):
        super().on_disconnect(by)

        # did we power down? then clear queues
        if self._shutdown_active:
            self._send_queue = queue.Queue()
            self._stale_lock.acquire()
            self._message_archive = {}
            self._stale_lock.release()
            self._shutdown_active = False

    def on_data_received(self, by: str | None, data: Any, command: str | None = None):
        """
        Handle received data

        Data is handed over as byte/bytearray and needs to be converted to
        utf8 strings. As packets can be fragmented, all data is written into
        a buffer and then checked for complete json expressions. Those are
        separated, converted to dict and processed with respect to saved
        message-ids. Processed data packets are dispatched one by one via
        callback.
        """

        def check_chunk(data):
            self.logger.debug(f'checking chunk {data}')
            try:
                json.loads(str(data, 'utf-8').strip())
                self.logger.debug('chunk checked ok')
                return True
            except Exception:
                self.logger.debug('chunk not valid json')
                return False

        self.logger.debug(f'data received before encode: {data}')

        # if isinstance(response, (bytes, bytearray)):
        #     response = str(response, 'utf-8').strip()

        self.logger.debug(f'adding response to buffer: {data}')
        self._receive_buffer += data

        datalist = []
        if b'}{' in self._receive_buffer:

            # split multi-response data into list items
            try:
                self.logger.debug('attempting to split buffer')
                tmplist = self._receive_buffer.replace(b'}{', b'}-#-{').split(b'-#-')
                datalist = list(OrderedDict((x, True) for x in tmplist).keys())
                self._receive_buffer = bytes()
            except Exception:
                pass
        # checking for bytes[0] == b'{' fails for some reason, so check for byte value instead... need to check char encoding?
        elif self._receive_buffer[0] == 123 and self._receive_buffer[-1] == 125 and check_chunk(self._receive_buffer):
            datalist = [self._receive_buffer]
            self._receive_buffer = b''
        elif self._receive_buffer:
            self.logger.debug(f'Buffer with incomplete response: {self._receive_buffer}')

        if datalist:
            self.logger.debug(f'received {len(datalist)} data items')

        # process all response items
        for ldata in datalist:
            self.logger.debug(f'Processing received data item #{datalist.index(ldata)}: {ldata}')

            try:
                jdata = json.loads(str(ldata, 'utf-8').strip())
            except Exception as err:
                if ldata == datalist[-1]:
                    self.logger.debug(f'returning incomplete data to buffer: {ldata}')
                    self._receive_buffer = ldata
                else:
                    self.logger.warning(f'Could not json.load data item {ldata} with error {err}')
                continue

            command = None

            # check messageid for replies
            if 'id' in jdata:
                response_id = jdata['id']

                # reply or error received, remove command
                if response_id in self._message_archive:
                    # possibly the command was resent and removed before processing the reply
                    # so let's 'try' at least...
                    try:
                        command = self._message_archive[response_id][1]
                        del self._message_archive[response_id]
                    except KeyError:
                        command = '(deleted)' if '_' not in response_id else response_id[response_id.find('_') + 1:]
                else:
                    command = None

                # log possible errors
                if 'error' in jdata:
                    self.logger.error(f'received error {jdata} in response to command {command}')
                elif command:
                    self.logger.debug(f'command {command} sent successfully')

            # process data
            if self._data_received_callback:
                self._data_received_callback(by, jdata, command)

        # check _message_archive for old commands - check time reached?
        if self._next_stale_check < time():

            # try to lock check routine, fail quickly if already locked = running
            if self._stale_lock.acquire(False):

                # we cannot deny access to self._message_archive as this would block sending
                # instead, copy it and check the copy
                stale_messages = self._message_archive.copy()
                remove_ids = []
                requeue_cmds = []

                # self._message_archive[message_id] = [time(), command, params, repeat]
                self.logger.debug(f'Checking for unanswered commands, last check was {int(time()) - self._last_stale_check} seconds ago, {len(self._message_archive)} commands saved')
                # !! self.logger.debug('Stale commands: {}'.format(stale_messages))
                for (message_id, (send_time, cmd, params, repeat)) in stale_messages.items():

                    if send_time + self._params[PLUGIN_ATTR_SEND_TIMEOUT] < time():

                        # reply timeout reached, check repeat count
                        if repeat <= self._params[PLUGIN_ATTR_SEND_RETRIES]:

                            # send again, increase counter
                            self.logger.info(f'Repeating unanswered command {cmd} ({params}), try {repeat + 1}')
                            requeue_cmds.append([cmd, params, message_id, repeat + 1])
                        else:
                            self.logger.info(f'Unanswered command {cmd} ({params}) repeated {repeat} times, giving up.')
                            remove_ids.append(message_id)

                for msgid in remove_ids:
                    # it is possible that while processing stale commands, a reply arrived
                    # and the command was removed. So just to be sure, 'try' and delete...
                    self.logger.debug(f'Removing stale msgid {msgid} from archive')
                    try:
                        del self._message_archive[msgid]
                    except KeyError:
                        pass

                # resend pending repeats - after original
                for (cmd, params, message_id, repeat) in requeue_cmds:
                    self._send_rpc_message(cmd, params, message_id, repeat)

                # set next stale check time
                self._last_stale_check = time()
                self._next_stale_check = self._last_stale_check + self._check_stale_cycle

                del stale_messages
                del requeue_cmds
                del remove_ids
                self._stale_lock.release()

            else:
                self.logger.debug(f'Skipping stale check {time() - self._last_stale_check} seconds after last check')

    def _send(self, data_dict: dict, **kwargs) -> Any:
        """
        wrapper to prepare json rpc message to send. extracts command, id, repeat and
        params (data) from data_dict and call send_rpc_message(command, params, id, repeat)
        """
        command = data_dict.get('command', data_dict.get('method', data_dict.get('payload')))
        message_id = data_dict.get('message_id', None)
        repeat = data_dict.get('repeat', 0)

        self._send_rpc_message(command, data_dict, message_id, repeat)

        # we don't return a response (this goes via on_data_received)
        return None

    def _send_rpc_message(self, command: str, ddict: dict = {}, message_id: str | None = None, repeat: int = 0):
        """
        Send a JSON RPC message.
        The JSON string is extracted from the supplied command and the given parameters.

        :param command: the command to be triggered
        :param ddict: dictionary with command data, e.g. keys 'params', 'data', 'headers', 'request_method'...
        :param message_id: the message ID to be used. If none, use the internal counter
        :param repeat: counter for how often the message has been repeated
        """
        self.logger.debug(f'preparing message to send command {command} with data {ddict}, try #{repeat}')

        if message_id is None:
            # safely acquire next message_id
            # !! self.logger.debug('Locking message id access ({})'.format(self._message_id))
            self._msgid_lock.acquire()
            self._message_id += 1
            new_msgid = self._message_id
            self._msgid_lock.release()
            message_id = str(new_msgid) + '_' + command
            # !! self.logger.debug('Releasing message id access ({})'.format(self._message_id))

        if not ddict:
            ddict = {}

        method = ddict.get('method', command)

        # create message packet
        new_data = {'jsonrpc': '2.0', 'id': message_id, 'method': method}

        if 'data' in ddict and ddict['data']:

            # ddict already contains 'data', we either have an old "ready" packet or new data
            if 'jsonrpc' not in ddict['data']:

                # we don't have a jsonrpc header, add new data to new header
                new_data['params'] = ddict['data']
            else:
                # jsonrpc header present, keep packet as is
                new_data = ddict['data']

        # set packet data
        ddict['data'] = new_data

        for key in self._params[JSON_MOVE_KEYS]:
            if key in ddict:
                if 'params' not in ddict['data']:
                    ddict['data']['params'] = {}
                ddict['data']['params'][key] = ddict[key]
                del ddict[key]

        # convert data if not using HTTP connections
        if 'request_method' not in ddict:

            try:
                # if 'payload' in ddict:
                #     ddict['payload'] += json.dumps(ddict['data'])
                # else:
                ddict['payload'] = json.dumps(ddict['data'])
            except Exception as e:
                raise ValueError(f'data {ddict["data"]} not convertible to JSON, aborting. Error was: {e}')

        # push message in queue
        self._send_queue.put([message_id, command, ddict, repeat])

        # try to actually send all queued messages
        self.logger.debug(f'processing queue - {self._send_queue.qsize()} elements')
        while not self._send_queue.empty():
            (message_id, command, ddict, repeat) = self._send_queue.get()

            self._message_archive[message_id] = [time(), command, ddict, repeat]

            self.logger.debug(f'sending queued msg {message_id} - {command} (#{repeat})')
            response = self._connection.send(ddict)
            if response:
                self.on_data_received('request', response)


class SDPProtocolResend(SDPProtocol):
    """
    Protocol supporting resend of command and checking reply_pattern

    This class implements a protocol to resend commands if reply does not align with reply_pattern
    """
    def __init__(self, data_received_callback: Callable | None, name: str | None = None, **kwargs):

        # init super, get logger
        super().__init__(data_received_callback, name, **kwargs)

        # get relevant plugin parameters
        self._send_retries = int(self._params.get(PLUGIN_ATTR_SEND_RETRIES) or 0)
        self._send_retries_cycle = int(self._params.get(PLUGIN_ATTR_SEND_RETRY_CYCLE) or 1)
        self._sending = {}
        self._sending_retries = {}
        self._sending_lock = Lock()

        # tell someone about our actual class
        self.logger.debug(f'protocol initialized from {self.__class__.__name__}')

    def on_connect(self, by: str | None = None):
        """
        When connecting, remove resend scheduler first. If send_retries is set > 0, add new scheduler with given cycle
        """
        super().on_connect(by)
        self.logger.info(f'connect called, resending queue is {self._sending}')
        if self._plugin.scheduler_get('resend'):  # type: ignore (circular import of SmartDevicePlugin)
            self._plugin.scheduler_remove('resend')  # type: ignore
        self._sending = {}
        if self._send_retries >= 1:
            self._plugin.scheduler_add('resend', self.resend, cycle=self._send_retries_cycle)  # type: ignore
            self.logger.dbghigh(f'Adding resend scheduler with cycle {self._send_retries_cycle}.')

    def on_disconnect(self, by: str | None = None):
        """
        Remove resend scheduler on disconnect
        """
        if self._plugin.scheduler_get('resend'):  # type: ignore
            self._plugin.scheduler_remove('resend')  # type: ignore
        self._sending = {}
        self.logger.info('on_disconnect called')
        super().on_disconnect(by)

    def _send(self, data_dict: dict, **kwargs) -> Any:
        """
        Send data, possibly return response

        :param data_dict: dict with raw data and possible additional parameters to send
        :type data_dict: dict
        :param kwargs: additional information needed for checking the reply_pattern
        :return: raw response data if applicable, None otherwise.
        """
        self._store_commands(kwargs.get('resend_info', {}), data_dict)
        self.logger.debug(f'Sending {data_dict}, kwargs {kwargs}')
        return self._connection.send(data_dict, **kwargs)

    def _store_commands(self, resend_info: dict, data_dict: dict) -> bool:
        """
        Store the command in _sending dict and the number of retries is _sending_retries dict

        :param resend_info: dict with command, returnvalue and read_command
        :type resend_info: dict
        :param data_dict: dict with raw data and possible additional parameters to send
        :type data_dict: dict
        :param kwargs: additional information needed for checking the reply_pattern
        :return: False by default, True if returnvalue is given in resend_info
        :rtype: bool
        """
        if resend_info is None:
            resend_info = {}
        else:
            resend_info['data_dict'] = data_dict
        if resend_info.get('send_retries') is None:
            resend_info['send_retries'] = self._send_retries
        if resend_info['send_retries'] <= 0:
            return False
        if resend_info.get('returnvalue') is not None:
            self._sending.update({resend_info.get('command'): resend_info})
            if resend_info.get('command') not in self._sending_retries:
                self._sending_retries.update({resend_info.get('command'): 1})
            self.logger.debug(f'Saving {resend_info}, resending queue is {self._sending}')
            return True
        return False

    def check_reply(self, command: str, value: Any) -> bool:
        """
        Check if the command is in _sending dict and if response is same as expected or not

        :param command: name of command
        :type command: str
        :param value: value the command (item) should be set to
        :type value: str
        :return: False by default, True if received expected response
        :rtype: bool
        """

        def convert_and_compare(value: Any, compare_value: Any) -> bool:
            value_type = type(value)
            if value_type == type(compare_value):
                return compare_value == value

            if value_type == int:
                try:
                    converted_value = int(compare_value)
                except ValueError:
                    return False
            elif value_type == float:
                try:
                    converted_value = float(compare_value)
                except ValueError:
                    return False
            elif value_type == bool:
                if compare_value.lower() == "true":
                    converted_value = True
                elif compare_value.lower() == "false":
                    converted_value = False
                else:
                    converted_value = None
            elif value_type == list:
                try:
                    converted_value = ast.literal_eval(compare_value)
                    if not isinstance(converted_value, list):
                        return False
                except (ValueError, SyntaxError):
                    return False
            elif value_type == dict:
                try:
                    converted_value = ast.literal_eval(compare_value)
                    if not isinstance(converted_value, dict):
                        return False
                except (ValueError, SyntaxError):
                    return False
            elif value_type == str:
                converted_value = compare_value
            else:
                return False
            return converted_value == value

        if command in self._sending:
            with self._sending_lock:
                # getting current retries for current command
                retry = self._sending_retries.get(command)
                # compare the expected returnvalue with the received value after aligning the type of both values
                compare = self._sending[command].get('returnvalue')
                compare = [compare] if not isinstance(compare, list) else compare
                for c in compare:
                    self.logger.debug(f'Comparing expected reply {c} ({type(c)}) with received value {value} ({type(value)}).')
                    lookup_log = ""
                    # check if expected value equals received value or both are None (only happens with lists in reply_pattern)
                    if isinstance(c, re.Pattern):
                        cond = re.search(c, str(value))
                    else:
                        cond = convert_and_compare(c, value)
                        lookup = self._sending[command].get('lookup')
                        if cond is False and lookup:
                            cond = c in lookup and lookup.get(c) == value
                            lookup_log = f" after checking lookup table {lookup}"
                            if cond is False:
                                lookup_ci = self._sending[command].get('lookup_ci')
                                if isinstance(value, str):
                                    value = value.lower()
                                cond = value in lookup_ci and c == value
                                lookup_log = f" after checking ci reverse lookup table {lookup_ci}"
                    if c is None or cond:
                        # remove command from _sending dict
                        self._sending.pop(command)
                        self._sending_retries.pop(command)
                        self.logger.debug(f'Got correct response for {command}{lookup_log}, '
                                          f'removing from send. Resending queue is {self._sending}')
                        return True
                if retry is not None and retry <= self._sending[command].get('send_retries'):
                    # return False and log info if response is not the same as the expected response
                    self.logger.debug(f'Should send again {self._sending[command]}...')
                    return False
        return False

    def resend(self):
        """
        Resend function that is scheduled with a given cycle.
        Send command again if response is not as expected and retries are < given retry parameter
        If expected response is not received after given retries, give up sending and query value by sending read_command
        """
        if self._sending:
            self.logger.debug(f"Resending queue is {self._sending}, retries {self._sending_retries}")
        with self._sending_lock:
            remove_commands = []
            # Iterate through resend queue
            for command in list(self._sending.keys()):
                retry = self._sending_retries.get(command, 1)
                sent = True
                if retry < self._sending[command].get('send_retries'):
                    self.logger.debug(f'Resending {command}, retries {retry}/{self._sending[command].get("send_retries")}.')
                    sent = self._send(self._sending[command].get("data_dict"))
                    self._sending_retries[command] = retry + 1
                elif retry >= self._sending[command].get('send_retries'):
                    sent = False
                if sent is False:
                    remove_commands.append(command)
                    self.logger.info(f"Giving up re-sending {command} after {retry} retries.")
                    if self._sending[command].get("read_cmd") is not None:
                        self.logger.info("Querying current value")
                        self._send(self._sending[command].get("read_cmd"))
            for command in remove_commands:
                self._sending.pop(command)
                self._sending_retries.pop(command)
