#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
# Copyright 2011-2013 Marcus Popp                          marcus@popp.mx
#########################################################################
#  This file is part of SmartHome.py.   http://smarthome.sourceforge.net/
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
#  along with SmartHome.py.  If not, see <http://www.gnu.org/licenses/>.
##########################################################################

import logging
import os

import lib.config

logger = logging.getLogger('')


class Logics():

    def __init__(self, smarthome, configfile):
        logger.info('Start Logics')
        self._sh = smarthome
        self._workers = []
        self._logics = {}
        self._bytecode = {}
        self.alive = True
        logger.debug("reading logics from {}".format(configfile))
        try:
            self._config = lib.config.parse(configfile)
        except Exception as e:
            logger.critical(e)
            return
        for name in self._config:
            logger.debug("Logic: {}".format(name))
            logic = Logic(self._sh, name, self._config[name])
            if hasattr(logic, 'bytecode'):
                self._logics[name] = logic
                self._sh.scheduler.add(name, logic, logic.prio, logic.crontab, logic.cycle)
            else:
                continue
            # plugin hook
            for plugin in self._sh._plugins:
                if hasattr(plugin, 'parse_logic'):
                    plugin.parse_logic(logic)
            # item hook
            if hasattr(logic, 'watch_item'):
                if isinstance(logic.watch_item, str):
                    logic.watch_item = [logic.watch_item]
                for entry in logic.watch_item:
                    itemexpr, sep, attribute = entry.partition(':')
                    itemexpr = itemexpr.strip()
                    if attribute != '':
                        attribute = attribute.strip()
                    else:
                        attribute = False
                    for item in self._sh.match_items(itemexpr):
                        if attribute:
                            if attribute in item.conf:
                                item.add_logic_trigger(logic)
                        else:
                            item.add_logic_trigger(logic)

    def __iter__(self):
        for logic in self._logics:
            yield logic

    def __getitem__(self, name):
        if name in self._logics:
            return self._logics[name]


class Logic():

    def __init__(self, smarthome, name, attributes):
        self._sh = smarthome
        self.name = name
        self.crontab = None
        self.cycle = None
        self.prio = 3
        self.last = None
        self.conf = attributes
        for attribute in attributes:
            vars(self)[attribute] = attributes[attribute]
        self.generate_bytecode()
        self.prio = int(self.prio)

    def id(self):
        return self.name

    def __str__(self):
        return self.name

    def __call__(self, caller='Logic', source=None, value=None, dest=None, dt=None):
        self._sh.scheduler.trigger(self.name, self, prio=self.prio, by=caller, source=source, dest=dest, value=value, dt=dt)

    def trigger(self, by='Logic', source=None, value=None, dest=None, dt=None):
        self._sh.scheduler.trigger(self.name, self, prio=self.prio, by=by, source=source, dest=dest, value=value, dt=dt)

    def generate_bytecode(self):
        if hasattr(self, 'filename'):
            filename = self._sh.base_dir + '/logics/' + self.filename
            if not os.access(filename, os.R_OK):
                logger.warning("{}: Could not access logic file ({}) => ignoring.".format(self.name, self.filename))
                return
            try:
                code = open(filename).read()
                code = code.lstrip('\ufeff')  # remove BOM
                self.bytecode = compile(code, self.filename, 'exec')
            except Exception as e:
                logger.exception("Exception: {}".format(e))
        else:
            logger.warning("{}: No filename specified => ignoring.".format(self.name))