#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
# Copyright 2016-2020   Martin Sinn                         m.sinn@gmx.de
# Copyright 2016        Christian Straßburg           c.strassburg@gmx.de
# Copyright 2012-2013   Marcus Popp                        marcus@popp.mx
#########################################################################
#  This file is part of SmartHomeNG.
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
#########################################################################

import logging
import os
import datetime
import time
import dateutil.parser
import json
import re

from ast import literal_eval
import pickle

from lib.constants import (CACHE_FORMAT, CACHE_JSON, CACHE_PICKLE, ATTRIBUTE_SEPARATOR)

logger = logging.getLogger(__name__)

#####################################################################
# Cast Methods
#####################################################################

def cast_str(value):
    if isinstance(value, (int, float)):
        value = str(value)
    if isinstance(value, str):
        return value
    else:
        raise ValueError


def cast_list(value):
    if isinstance(value, str):
        try:
            value = literal_eval(value)
        except:
            pass
    if isinstance(value, list):
        return value
    else:
        raise ValueError


def cast_dict(value):
    if isinstance(value, str):
        try:
            value = literal_eval(value)
        except:
            pass
    if isinstance(value, dict):
        return value
    else:
        raise ValueError


def cast_foo(value):
    return value


# TODO: Candidate for Utils.to_bool()
# write testcase and replace
# -> should castng be restricted like this or handled exactly like Utils.to_bool()?
#    Example: cast_bool(2) is False, Utils.to_bool(2) is True

def cast_bool(value):
    if type(value) in [bool, int, float]:
        if value in [False, 0]:
            return False
        elif value in [True, 1]:
            return True
        else:
            raise ValueError
    elif type(value) in [str, str]:
        if value.lower() in ['0', 'false', 'no', 'off', '']:
            return False
        elif value.lower() in ['1', 'true', 'yes', 'on']:
            return True
        else:
            raise ValueError
    else:
        raise TypeError


def cast_scene(value):
    return int(value)


def cast_num(value):
    """
    cast a passed value to int or float

    :param value: numeric value to be casted, passed as str, float or int
    :return: numeric value, passed as int or float
    """
    if isinstance(value, str):
        value = value.strip()
    if value == '':
        return 0
    if isinstance(value, float):
        return value
    try:
        return int(value)
    except:
        pass
    try:
        return float(value)
    except:
        pass
    raise ValueError


#####################################################################
# Methods for handling of duration_value strings
#####################################################################

def split_duration_value_string(value, ATTRIB_COMPAT_DEFAULT):
    """
    splits a duration value string into its three components

    components are:
    - time
    - value
    - compat

    :param value: raw attribute string containing duration, value (and compatibility)
    :return: three strings, representing time, value and compatibility attribute
    """
    if value.find(ATTRIBUTE_SEPARATOR) >= 0:
        time, __, attrvalue = value.partition(ATTRIBUTE_SEPARATOR)
        attrvalue, __, compat = attrvalue.partition(ATTRIBUTE_SEPARATOR)
    elif value.find('=') >= 0:
        time, __, attrvalue = value.partition('=')
        attrvalue, __, compat = attrvalue.partition('=')
    else:
        time = value
        attrvalue = None
        compat = ''

    time = time.strip()
    if attrvalue is not None:
        attrvalue = attrvalue.strip()
    compat = compat.strip().lower()
    if compat == '':
        compat = ATTRIB_COMPAT_DEFAULT

    # remove quotes, if present
    if value != '' and ((value[0] == "'" and value[-1] == "'") or (value[0] == '"' and value[-1] == '"')):
        value = value[1:-1]
    return (time, attrvalue, compat)


def join_duration_value_string(time, value, compat=''):
    """
    joins a duration value string from its three components

    components are:
    - time
    - value
    - compat

    :param time: time (duration) parrt for the duration_value_string
    :param value: value (duration) parrt for the duration_value_string
    """
    result = str(time)
    if value != '' or compat != '':
        result = result + ' ='
        if value != '':
            result = result + ' ' + value
        if compat != '':
           result = result + ' = ' + compat
    return result


#####################################################################
# Cache Methods
#####################################################################

def json_serialize(obj):
    """
    helper method to convert values to json serializable formats
    """
    import datetime
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    raise TypeError("Type not serializable")

def json_obj_hook(json_dict):
    """
    helper method for json deserialization
    """
    import dateutil
    for (key, value) in json_dict.items():
        try:
            json_dict[key] = dateutil.parser.parse(value)
        except Exception as e :
            pass
    return json_dict


def cache_read(filename, tz, cformat=CACHE_FORMAT):
    ts = os.path.getmtime(filename)
    dt = datetime.datetime.fromtimestamp(ts, tz)
    value = None

    if cformat == CACHE_PICKLE:
        with open(filename, 'rb') as f:
            value = pickle.load(f)

    elif cformat == CACHE_JSON:
        with open(filename, 'r', encoding='UTF-8') as f:
            value = json.load(f, object_hook=json_obj_hook)

    return (dt, value)

def cache_write(filename, value, cformat=CACHE_FORMAT):
    try:
        if cformat == CACHE_PICKLE:
            with open(filename, 'wb') as f:
                pickle.dump(value,f)

        elif cformat == CACHE_JSON:
            with open(filename, 'w', encoding='UTF-8') as f:
                json.dump(value,f, default=json_serialize)
    except IOError:
        logger.warning("Could not write to {}".format(filename))


#####################################################################
# Fade Method
#####################################################################
def fadejob(item, dest, step, delta, stop_fade=None, continue_fade=None, instant_set=True):
    def check_external_change(entry_type, entry_value):
        matches = []
        for pattern in entry_value:
            regex = re.compile(pattern, re.IGNORECASE)
            if regex.match(item.property.last_change_by):
                if entry_type == "stop_fade":
                    matches.append(True)  # Match in stop_fade, should stop
                else:
                    matches.append(False)  # Match in continue_fade, should continue fading
            else:
                if entry_type == "continue_fade":
                    matches.append(True)  # No match in continue_fade -> we can stop
                else:
                    matches.append(False)  # No match in stop_fade -> keep fading
        return matches
    def do_fade(start_value=None, last_update_time=None, instant_set=True):
        if last_update_time is None:
            last_update_time = time.time()
        fade_value = start_value if start_value is not None else item._value
        # print(f"{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]} Fader {item}: Last update time {last_update_time}, start value {start_value} fade value {fade_value}")

        while (item._value < dest if item._value < dest else item._value > dest) and item._fading:
            current_time = time.time()
            elapsed_time = current_time - last_update_time

            # Only fade if the full delta interval has passed
            if elapsed_time >= delta or instant_set is True:
                instant_set = False
                if start_value is not None:
                    fade_value += (step if start_value < dest else -step)
                    start_value = None
                else:
                    fade_value += (step if item._value < dest else -step)
                # print(f"{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]} Fader {item}: Fading... value is {fade_value}, including: N/A, excluding: N/A")
                item(fade_value, 'fader')
                last_update_time = current_time
            remaining_time = delta - elapsed_time
            if remaining_time > 0:
                item._lock.acquire()
                item._lock.wait(remaining_time)
                item._lock.release()

            if not item._fading:  # Check again after waiting, before applying the next fade
                break
        return fade_value, last_update_time

    def run_fade(start_value=None, last_update_time=None, instant_set=True):
        if item._fading:
            return
        else:
            item._fading = True
        start_value, last_update_time = do_fade(start_value, last_update_time, instant_set)

        if not item._fading and item.property.last_change_by != "fader:None":
            stopping = check_external_change("stop_fade", stop_fade) if stop_fade else [False]
            continuing = check_external_change("continue_fade", continue_fade) if continue_fade else [False]

            # If stop_fade is set and there's a match, stop fading immediately
            if stop_fade and True in stopping:
                # print(f"{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]} Fader {item}: Stopping fade loop, match in stop_fade for {item.property.last_change_by}")
                return

            # If continue_fade is set and there is no match, stop fading immediately
            if continue_fade and False not in continuing:
                # print(f"{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]} Fader {item}: Stopping fade loop, no match in continue_fade for {item.property.last_change_by}")
                return

            # If nothing is set, stop (original behaviour)
            if not continue_fade and not stop_fade:
                # print(f"{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]} Fader {item}: Stopping fade loop, no conditions set")
                return

            # Otherwise, continue fading
            # print(f"{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]} Fader {item}: Continuing fade loop, match in continue_fade for {item.property.last_change_by}")
            run_fade(start_value, last_update_time, instant_set=instant_set)
    run_fade(None, None, instant_set=instant_set)
