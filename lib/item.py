#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
# Copyright 2012-2013 Marcus Popp                          marcus@popp.mx
#########################################################################
#  This file is part of SmartHome.py.
#
#  SmartHome.py is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHome.py is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHome.py. If not, see <http://www.gnu.org/licenses/>.
#########################################################################

import logging
import threading
import datetime
import pickle

logger = logging.getLogger('')


class Item():
    _defaults = {'num': 0, 'str': '', 'bool': False, 'list': [], 'dict': {}, 'foo': None, 'scene': ''}

    def __init__(self, smarthome, parent, path, config):
        # basic attributes
        self._path = path
        self._name = path
        self._value = None
        self._type = None
        # public attributes
        self.conf = {}
        self._last_change = smarthome.now()
        self._prev_change = self._last_change
        self._changed_by = 'Init'
        # special attributes
        self._sh = smarthome
        if hasattr(smarthome, '_item_change_log'):
            self._change_logger = logger.info
        else:
            self._change_logger = logger.debug
        self._lock = threading.Condition()
        self._cache = False
        self._crontab = None
        self._cycle = None
        self._eval = False
        self._threshold = False
        self._enforce_updates = False
        self._parent = parent
        self._sub_items = []
        self._methods_to_trigger = []
        self._logics_to_trigger = []
        self._items_to_trigger = []
        self.__fade = False
        self._autotimer = False
        self.parse(smarthome, parent, path, config)

    def parse(self, smarthome, parent, path, config):
        # parse config
        for attr in config:
            if not isinstance(config[attr], dict):  # attribute
                if attr == 'type':
                    self._type = config[attr]
                elif attr == 'value':
                    self._value = config[attr]
                elif attr == 'name':
                    self._name = config[attr]
                elif attr == 'cache':
                    try:
                        self._cache = self._return_bool(config[attr])
                    except:
                        logger.error("Item '{0}' problem parsing '{1}'.Ignoring Item!".format(path, config[attr]))
                        return
                elif attr == 'enforce_updates':
                    try:
                        self._enforce_updates = self._return_bool(config[attr])
                    except:
                        logger.error("Item '{0}' problem parsing '{1}'.Ignoring Item!".format(path, config[attr]))
                        return
                elif attr == 'threshold':
                    self._threshold = config[attr]
                elif attr == 'eval':
                    if isinstance(config[attr], list):
                        self._eval = ', '.join(config[attr])  # join together
                    else:
                        self._eval = config[attr]
                elif attr == 'eval_trigger':
                    if isinstance(config[attr], str):
                        self.conf[attr] = [config[attr], ]
                    else:
                        self.conf[attr] = config[attr]
                elif attr == 'cycle':
                    self._cycle = config[attr]
                elif attr == 'crontab':
                    if isinstance(config[attr], list):
                        self._crontab = ','.join(config[attr])
                    else:
                        self._crontab = config[attr]
                elif attr == 'autotimer':
                    time, sep, value = config[attr].partition('=')
                    if value is not None:
                        self._autotimer = time, value
                else:
                    self.conf[attr] = config[attr]
        for attr in config:
            if isinstance(config[attr], dict):  # sub item
                sub_path = self._path + '.' + attr
                sub_item = smarthome.return_item(sub_path)
                if sub_item is None:  # new item
                    sub_item = Item(smarthome, self, sub_path, config[attr])
                    vars(self)[attr] = sub_item
                    smarthome.add_item(sub_path, sub_item)
                    self._sub_items.append(sub_item)
                else:  # existing item
                    sub_item.parse(smarthome, self, sub_path, config[attr])
        if self._type is not None:
            if self._type not in self._defaults:
                logger.warning("Item {0}: type '{1}' unknown. Please use one of: {2}.".format(path, self._type, ', '.join(list(self._defaults.keys()))))
                return
            if self._value is None:
                self._value = self._defaults[self._type]
            else:
                try:
                    self._value = getattr(self, '_return_' + self._type)(self._value)
                except:
                    logger.error("Item '{0}': value ({1}) does not match type ({2}). Ignoring!".format(path, self._value, self._type))
                    return
        else:
            #logger.debug("Item '{0}': No type specified.".format(self._path))
            return
        if self._cache:
            self._value = self._db_read()
        if self._threshold:
            low, sep, high = self._threshold.rpartition(':')
            if not low:
                low = high
            self._th_low = float(low)
            self._th_high = float(high)
            logger.debug("Item '{0}': set threshold => low: {1} high: {2}".format(self._path, self._th_low, self._th_high))
            self._th = False
        if self._crontab is not None or self._cycle is not None:
            self._sh.scheduler.add(self.id(), self, cron=self._crontab, cycle=self._cycle)
        for plugin in self._sh.return_plugins():
            if hasattr(plugin, 'parse_item'):
                update = plugin.parse_item(self)
                if update:
                    self.add_trigger_method(update)

    def add_trigger_method(self, method):
        self._methods_to_trigger.append(method)

    def init_prerun(self):
        if 'eval_trigger' in self.conf:
            triggers = []
            for trigger in self.conf['eval_trigger']:
                triggers += self._sh.match_items(trigger)
            for item in triggers:
                if item != self:  # prevent loop
                    item._items_to_trigger.append(self)
            if self._eval:
                items = ['sh.' + x.id() + '()' for x in triggers]
                if self._eval == 'and':
                    self._eval = ' and '.join(items)
                elif self._eval == 'or':
                    self._eval = ' or '.join(items)
                elif self._eval == 'sum':
                    self._eval = ' + '.join(items)
                elif self._eval == 'avg':
                    self._eval = '({0})/{1}'.format(' + '.join(items), len(items))

    def init_run(self):
        if 'eval_trigger' in self.conf:
            if self._eval:
                self._sh.trigger(name=self._path, obj=self._run_eval, by='Init')
            del(self.conf['eval_trigger'])

    def last_change(self):
        return self._last_change

    def prev_change(self):
        return self._prev_change

    def changed_by(self):
        return self._changed_by

    def age(self):
        delta = self._sh.now() - self._last_change
        return delta.total_seconds()

    def _run_eval(self, value=None, caller='Eval', source=None, dest=None):
        if self._eval:
            sh = self._sh  # noqa
            try:
                value = eval(self._eval)
            except Exception as e:
                logger.warning("Problem evaluating {0}: {1}".format(self._eval, e))
            else:
                self._update(value, caller, source)

    def __del__(self):
        # dummy for garbage collection
        logger.warning("Deleting Item: {0}".format(self._path))

    def set(self, value, caller='Logic', source=None, dest=None):
        try:
            value = getattr(self, '_return_' + self._type)(value)
        except:
            logger.error("Item '{0}': value ({1}) does not match type ({2}). Via {3} {4} => {5}".format(self._path, value, self._type, caller, source, dest))
            return
        self._lock.acquire()
        self._value = value
        self._lock.release()
        self._change_logger("{0} = {1} via {2} {3} {4}".format(self._path, value, caller, source, dest))

    def __call__(self, value=None, caller='Logic', source=None, dest=None):
        if value is None or self._type is None:
            return self._value
        try:
            value = getattr(self, '_return_' + self._type)(value)
        except:
            try:
                logger.error("Item '{0}': value ({1}) does not match type ({2}). Via {3} {4}".format(self._path, value, self._type, caller, source))
            except:
                pass
            return
        if self._eval:
            args = {'value': value, 'caller': caller, 'source': source, 'dest': dest}
            self._sh.trigger(name=self._path + '-eval', obj=self._run_eval, value=args, by=caller, source=source, dest=dest)
        else:
            self._update(value, caller, source, dest)

    def _update(self, value=None, caller='Logic', source=None, dest=None):
        try:
            value = getattr(self, '_return_' + self._type)(value)
        except:
            logger.error("Item '{0}': value ({1}) does not match type ({2}). Via {3} {4} => {5}".format(self._path, value, self._type, caller, source, dest))
            return
        self._lock.acquire()
        if value != self._value or self._enforce_updates:  # value change
            if caller != "fade":
                self.__fade = False
                self._lock.notify_all()
                self._change_logger("{0} = {1} via {2} {3}".format(self._path, value, caller, source))
            self._value = value
            delta = self._sh.now() - self._last_change
            self._prev_change = delta.total_seconds()
            self._last_change = self._sh.now()
            self._changed_by = "{0}:{1}".format(caller, source)
            self._lock.release()
            for update_plugin in self._methods_to_trigger:
                try:
                    update_plugin(self, caller, source, dest)
                except Exception as e:
                    logger.exception("{} problem running {} {}".format(self._path, update_plugin, e))
            if self._threshold and self._logics_to_trigger:
                if self._th and self._value <= self._th_low:  # cross lower bound
                    self._th = False
                    self._trigger_logics()
                elif not self._th and self._value >= self._th_high:  # cross upper bound
                    self._th = True
                    self._trigger_logics()
            elif self._logics_to_trigger:
                self._trigger_logics()
            for item in self._items_to_trigger:
                args = {'value': value, 'source': self._path}
                self._sh.trigger(name=item.id(), obj=item._run_eval, value=args, by=caller, source=source, dest=dest)
            if self._cache and not self.__fade:
                self._db_update(value)
        else:
            self._lock.release()
        if self._autotimer is not False and caller is not 'Autotimer':
            _time, _value = self._autotimer
            self.timer(_time, _value, True)

    def __iter__(self):
        for item in self._sub_items:
            yield item

    def return_children(self):
        for item in self._sub_items:
            yield item

    def return_parent(self):
        return self._parent

    def __setitem__(self, item, value):
        vars(self)[item] = value

    def __getitem__(self, item):
        return vars(self)[item]

    def _db_read(self):
        try:
            with open(self._sh._cache_dir + self._path, 'rb') as f:
                return pickle.load(f)
        except IOError:
            logger.info("Could not read {0}{1}".format(self._sh._cache_dir, self._path))
            try:
                return getattr(self, '_return_' + self._type)(0)
            except:
                return False
        except EOFError:
            logger.info("{0}{1} is empty".format(self._sh._cache_dir, self._path))
            try:
                return getattr(self, '_return_' + self._type)(0)
            except:
                return False

    def _db_update(self, value):
        try:
            with open(self._sh._cache_dir + self._path, 'wb') as f:
                pickle.dump(value, f)
        except IOError:
            logger.warning("Could not write to {0}{1}".format(self._sh._cache_dir, self._path))

    # don't compare value, compare object: if you want to compare value, do check item()
    #def __cmp__(self, compare):
    #    return cmp(self._value, compare)

    def id(self):
        return self._path

    def __bool__(self):
        return self._value

    def __str__(self):
        return self._name

    def __repr__(self):
        return "Item: {0}".format(self._value)

    def add_logic_trigger(self, logic):
        self._logics_to_trigger.append(logic)

    def _trigger_logics(self):
        for logic in self._logics_to_trigger:
            logic.trigger('Item', self._path, self._value)

    def _return_str(self, value):
        if isinstance(value, str):
            return value
        else:
            raise ValueError

    def _return_list(self, value):
        if isinstance(value, list):
            return value
        else:
            raise ValueError

    def _return_dict(self, value):
        if isinstance(value, dict):
            return value
        else:
            raise ValueError

    def _return_foo(self, value):
        return value

    def _return_bool(self, value):
        if type(value) in [bool, int, float]:
            if value in [False, 0]:
                return False
            elif value in [True, 1]:
                return True
            else:
                raise ValueError
        elif type(value) in [str, str]:
            if value.lower() in ['0', 'false', 'no', 'off']:
                return False
            elif value.lower() in ['1', 'true', 'yes', 'on']:
                return True
            else:
                raise ValueError
        else:
            raise TypeError

    def _return_scene(self, value):
        return int(value)

    def _return_num(self, value):
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

    def autotimer(self, time=None, value=None):
        if time is not None and value is not None:
            self._autotimer = time, value
        else:
            self._autotimer = False

    def timer(self, time, value, auto=False):
        if isinstance(time, str):
            time = time.strip()
            if time.endswith('m'):
                time = int(time.strip('m')) * 60
            else:
                time = int(time)
        if isinstance(value, str):
            value = value.strip()
        if auto:
            caller = 'Autotimer'
            self._autotimer = time, value
        else:
            caller = 'Timer'
        next = self._sh.now() + datetime.timedelta(seconds=time)
        self._sh.scheduler.add(self.id() + '-Timer', self.__call__, value={'value': value, 'caller': caller}, next=next)

    def fade(self, dest, step=1, delta=1):
        dest = float(dest)
        self._sh.trigger('fade', self._fadejob, value={'dest': dest, 'step': step, 'delta': delta})

    def _fadejob(self, dest, step, delta):
        if self.__fade:
            return
        else:
            self.__fade = True
        if self._value < dest:
            while (self._value + step) < dest and self.__fade:
                self(self._value + step, 'fade')
                self._lock.acquire()
                self._lock.wait(delta)
                self._lock.release()
        else:
            while (self._value - step) > dest and self.__fade:
                self(self._value - step, 'fade')
                self._lock.acquire()
                self._lock.wait(delta)
                self._lock.release()
        if self.__fade:
            self.__fade = False
            self(dest)