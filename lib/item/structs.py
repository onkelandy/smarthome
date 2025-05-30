#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
# Copyright 2018-2023   Martin Sinn                         m.sinn@gmx.de
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
import collections
import os
import copy

import lib.shyaml as shyaml
from lib.config import sanitize_items
from lib.constants import (YAML_FILE, BASE_STRUCT, DIR_STRUCTS, DIR_ETC)

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------
#   Following methods handle structs
# -----------------------------------------------------------------------------------------

struct_merge_lists = True


class Structs():

    struct_merge_lists = True

    _struct_definitions = collections.OrderedDict()     # definitions of item structures
    _finalized_structs = []                             # struct names are appended to this list, if they do not
                                                        # contain any 'struct' attributes any more

    def __init__(self, smarthome):
        self.logger = logging.getLogger(__name__)
        self._sh = smarthome
        self.save_joined_structs = False
        self.etc_dir = self._sh.get_config_dir(DIR_ETC)
        self.structs_dir = self._sh.get_config_dir(DIR_STRUCTS)


    def return_struct_definitions(self, all=True):
        """
        Return all loaded structure template definitions

        :return:
        :rtype: dict
        """
        result = {}
        for struct in self._struct_definitions:
            try:
                _, struct_name = struct.split('.')
            except ValueError:
                struct_name = struct
            if struct_name.startswith('_'):
                self.logger.info(f"return_struct_definitions: Internal struct {struct}")
                if all:
                    result[struct] = self._struct_definitions[struct]
            else:
                result[struct] = self._struct_definitions[struct]

        return result

# ==========================================================================
# The following methods are used to read the struct definitions at startup


    def load_definitions_from_etc(self):
        """
        Read in all struct definitions from ../etc directory

        - structs are read in from ../etc/struct.yaml by this procedure
        - further structs are read in from ../etc/struct_<prefix>.yaml by this procedure
        """
        self.load_struct_definitions_from_file(self._sh.get_config_dir(DIR_ETC), BASE_STRUCT + YAML_FILE, '')

        # look for further struct files
        file_list = os.listdir(self.etc_dir)
        for filename in file_list:
            if filename.startswith(BASE_STRUCT + '_') and filename.endswith(YAML_FILE):
                key_prefix = 'my.' + filename[len(BASE_STRUCT):-len(YAML_FILE)]
                self.load_struct_definitions_from_file(self.etc_dir, filename, key_prefix)
        return


    def migrate_one_file(self, filename: str, dest_fn: str):
        """

        :param filename: source filename
        :param dest_fn: destination filename
        """
        import shutil

        if os.path.isfile(os.path.join(self.structs_dir, dest_fn)):
            self.logger.warning(f"Cannot migrate structs definition file `{filename}` to structs directory. {dest_fn} already exists.")
        else:
            self.logger.notice(f"Migrating struct definition file from etc/{filename} to structs/{dest_fn}")
            shutil.move(os.path.join(self.etc_dir, filename), os.path.join(self.structs_dir, dest_fn))


    def migrate_to_structs_dir(self):
        """
        Migrate structs definition files from ../etc directory to ../structs directory
        """
        fl = os.listdir(self.etc_dir)
        for filename in fl:
            if filename.startswith(BASE_STRUCT + '_') and filename.endswith(YAML_FILE):
                dest_fn = filename[len(BASE_STRUCT):]
                self.migrate_one_file(filename, dest_fn)

        filename = BASE_STRUCT + YAML_FILE
        if os.path.isfile(os.path.join(self.etc_dir, filename)):
            dest_fn = 'global_structs.yaml'
            self.migrate_one_file(filename, dest_fn)

        return


    def load_definitions_from_structs(self):
        """
        Read in all struct definitions from ../structs directory

        - structs are read in from ../structs/<name>.yaml by this procedure
        """
        self.load_struct_definitions_from_file(self._sh.get_config_dir(DIR_ETC), BASE_STRUCT + YAML_FILE, '')
        if os.path.isdir(self.structs_dir):
            # look for struct files
            file_list = os.listdir(self.structs_dir)
            for filename in file_list:
                if not (filename.startswith('.')) and filename.endswith(YAML_FILE):
                    if filename == 'global_structs.yaml':
                        key_prefix = ''
                    else:
                        key_prefix = 'my.' + filename[:-len(YAML_FILE)]
                    self.load_struct_definitions_from_file(self.structs_dir, filename, key_prefix)
        else:
            self.logger.notice("../" + DIR_STRUCTS + " does not exist")
        return


    def load_struct_definitions(self):
        """
        Read in all struct definitions from ../etc directory before reading item definitions

        structs are merged into the item tree in lib.config

        - plugin-structs are read in from metadata file of plugins while loading plugins
        - other structs are read in from ../etc/struct.yaml by this procedure
        - further structs are read in from ../etc/struct_<prefix>.yaml by this procedure
        """
        import time
        totalstart = time.perf_counter()
        start = time.perf_counter()

        self.migrate_to_structs_dir()

        self.load_definitions_from_structs()
        self.load_definitions_from_etc()

        end = time.perf_counter()
        duration = end - start
        self.logger.dbghigh(f"load_struct_definitions: time load_struct_definitions_from_file(): Duration={duration}")

        # Now that all structs have been loaded,
        # resolve struct references in structs and fill in the content of the struct

        do_resolve = True
        run = 0
        while do_resolve:
            do_resolve = False
            run += 1
            self.logger.dbghigh(f"load_struct_definitions: {run}. run of struct resolve")

            import time
            start = time.perf_counter()
            for struct_name in self._struct_definitions:
                if struct_name not in self._finalized_structs:
                    # self.logger.dbghigh(f"- processing struct '{struct_name}'")

                    if self.traverse_struct(struct_name):
                        do_resolve = True
                    else:
                        self._finalized_structs.append(struct_name)
                        self.logger.dbghigh(f"load_struct_definitions: Finalized struct '{struct_name}'")

            end = time.perf_counter()
            duration = end - start
            self.logger.dbghigh(f"load_struct_definitions: time traverse all structs: Duration={duration}")


        # for Testing: Save structure of joined item structs
        import time
        if self.save_joined_structs:
            start = time.perf_counter()
            self.logger.info(f"load_itemdefinitions(): For testing the joined item structs are saved to {os.path.join(self.etc_dir, 'structs_joined.yaml')}")
            shyaml.yaml_save(os.path.join(self.etc_dir, 'structs_joined.yaml'), self._struct_definitions)
            end = time.perf_counter()
            duration = end - start
            self.logger.dbghigh(f"load_struct_definitions: time yaml_save(): Duration={duration}")

        totalend = time.perf_counter()
        duration = totalend - totalstart
        self.logger.dbghigh(f"load_struct_definitions: time Total duration={duration}")

        return


    def load_struct_definitions_from_file(self, source_dir, filename, key_prefix):
        """
        Loads struct definitions from a file

        :param source_dir: path to etc directory of SmartHomeNG
        :param filename: filename to load struct definition(s) from
        :param key_prefix: prefix to be used when adding struct(s) to loaded definitions
        """
        if key_prefix == '':
            self.logger.info(f"Loading struct file '{filename}' without key-prefix")
        else:
            self.logger.info(f"Loading struct file '{filename}' with key-prefix '{key_prefix}'")

        # Read in item structs from ../source_dir/<filename>.yaml
        struct_definitions = shyaml.yaml_load(os.path.join(source_dir, filename), ordered=True, ignore_notfound=True)

        # if valid struct definition file etc/<filename>.yaml ist found
        if struct_definitions is not None:
            if isinstance(struct_definitions, collections.OrderedDict):
                for key in struct_definitions:
                    if key_prefix == '':
                        struct_name = key
                    else:
                        struct_name = key_prefix + '.' + key

                    # cleanup struct data
                    struct = struct_definitions[key]
                    sanitize_items(struct, os.path.join(source_dir, filename))

                    self.add_struct_definition('', struct_name, struct, source_dir)
            else:
                self.logger.error(f"load_itemdefinitions(): Invalid content in {filename}: struct_definitions = '{struct_definitions}'")

        return


    def add_struct_definition(self, plugin_name, struct_name, struct, from_dir='', optional=False):
        """
        Add a single struct definition

        called from load_struct_definitions_from_file when reading in item structs from ../etc/<filename>>.yaml,
        ../structs/<filename>>.yaml or from lib.plugin when reading in plugin-metadata which contains structs

        :param plugin_name: Name of the plugin if called from lib.plugin else an empty string
        :param struct_name: Name of the struct to add
        :param struct: definition of the struct to add
        :param optional: only add if not yet present
        :return:
        """
        if plugin_name == '':
            name = struct_name
        else:
            name = plugin_name + '.' + struct_name

        # self.logger.debug(f"add_struct_definition: struct '{name}' = {dict(struct)}")
        if self._struct_definitions.get(name, None) is None:
            self._struct_definitions[name] = struct
            self._struct_definitions[name]['__struct_is_optional'] = optional
        elif self._struct_definitions[name].get('__struct_is_optional', False) and not optional:
            # overwrite optional structs if current struct is not optional
            self._struct_definitions[name] = struct
            self._struct_definitions[name]['__struct_is_optional'] = optional
            self.logger.info(f'overwriting optional struct {name}')
        else:
            if from_dir != 'plugins':
                self.logger.error(f"add_struct_definition: struct '{name}' already loaded - ignoring definition from {from_dir}")
        return


#   ==========================================================================
#   The following methods are used to resolve nested struct definitions
#   after loading all struct definitions from file(s)


    def traverse_struct(self, struct_name):
        """
        Traverses through a struct to find struct-attributes and replace them with the references struct(s)

        :param struct_name: Name of the struct to traverse

        :return: True, if the struct has been modified (references have been replaces)
        """
        struct = self._struct_definitions.get(struct_name, None)
        if struct is None:
            self.logger.warning(f"traverse_struct: struct {struct_name} not found")
            return

        prefixes = struct_name.split('.')
        if prefixes[0] == 'my':
            key_prefix = prefixes[0] + '.' + prefixes[1]
        else:
            # set plugin-name as key_prefix
            key_prefix = prefixes[0]

        self.logger.dbghigh(f"traverse_struct: struct={struct_name}, prefixes={prefixes}, key_prefix={key_prefix}")
        new_struct = self.process_struct_node(struct, struct_name, key_prefix=key_prefix)
        if new_struct is not None:
            self.logger.dbghigh(f"traverse_struct: struct '{struct_name}' was updated")
            self.logger.dbghigh(f"traverse_struct: new_struct {new_struct}")
            self._struct_definitions[struct_name] = new_struct
            return True

        return False


    def process_struct_node(self, node, node_name='?', key_prefix='', level=0):

        spaces = " " * level
        structs_expanded = False
        for element in dict(node):
            if isinstance(node[element], dict):
                # self.logger.dbghigh(f"process_struct_node: {spaces}node {element}:")
                newnode = self.process_struct_node(node[element], node_name=element, key_prefix=key_prefix, level=level+4)
                if newnode is not None:
                    node[element] = newnode
                    structs_expanded = True
            elif element == 'struct':
                self.logger.dbghigh(f"process_struct_node: {spaces}{node_name}: 'struct' attribute found: {node[element]}")
                # self.logger.dbghigh(f"process_struct_node: {spaces}node   = {dict(node)}")
                substruct_names = node[element]
                if isinstance(substruct_names, str):
                    substruct_names = [substruct_names]
                node = self.resolve_structs(node, node_name, substruct_names, key_prefix)
                structs_expanded = True
                # self.logger.dbghigh(f"process_struct_node: {spaces}node   = {dict(node)}")
                del (node['struct'])
                self.logger.dbghigh(f"process_struct_node: Done, removed 'struct' attribute from struct '{node_name}'")
            else:
                pass
                # self.logger.dbghigh(f"process_struct_node: {spaces}leaf {element}={node[element]}")

        if structs_expanded:
            return node


    def resolve_structs(self, struct, struct_name, substruct_names, key_prefix):
        """
        Resolve a struct reference within a struct

        if the struct definition that is to be inserted contains a struct reference, it is resolved first

        :param struct:          struct that contains a struct reference
        :param struct_name:     name of the struct that contains a struct reference
        :param substruct_name:  name of the sub-struct definition that shall be inserted
        """

        self.logger.info(f"resolve_structs: struct_name='{struct_name}', substruct_names='{substruct_names}'")

        new_struct = collections.OrderedDict()
        structentry_list = list(struct.keys())
        for structentry in structentry_list:
            # copy all existing attributes and sub-entrys of the struct
            if new_struct.get(structentry, None) is None:
                self.logger.dbgmed(f"resolve_structs: - copy attribute structentry='{structentry}', value='{struct[structentry]}'")
                new_struct[structentry] = copy.deepcopy(struct[structentry])
            else:
                self.logger.dbghigh(f"resolve_structs: - key='{structentry}', value is ignored'")
            if structentry == 'struct':
                for substruct_name in substruct_names:
                    # for every substruct
                    self.merge_substruct_to_struct(new_struct, substruct_name, struct_name, key_prefix)

        return new_struct


    def merge_substruct_to_struct(self, main_struct, substruct_name, main_struct_name='?', key_prefix=''):
        """

        :param main_struct:
        :param substruct_name:
        :param main_struct_name:
        :return:
        """

        self.logger.dbgmed(f"merge_substruct_to_struct: substruct_name='{substruct_name}' -> main_struct='{main_struct_name}'")
        if substruct_name.startswith('.'):
            # referencing a struct from same definition file
            substruct_name = key_prefix + substruct_name
        substruct = self._struct_definitions.get(substruct_name, None)
        if substruct is None:
            self.logger.error(f"struct '{substruct_name}' not found in structdefinitions (used in struct '{main_struct_name}') - key_prefix={key_prefix}")
        else:
            # merge the sub-struct to the main-struct key by key
            for key in substruct:
                if key == '__struct_is_optional':
                    continue
                if main_struct.get(key, None) is None:
                    self.logger.dbglow(f" - add key='{key}', value='{substruct[key]}' -> new_struct='{dict(main_struct)}'")
                    main_struct[key] = copy.deepcopy(substruct[key])
                elif isinstance(main_struct.get(key, None), dict):
                    self.logger.dbglow(f" - merge key='{key}', value='{substruct[key]}' -> new_struct='{dict(main_struct)}'")
                    self.merge(substruct[key], main_struct[key], substruct_name + '.' + key, main_struct_name + '.' + key)
                elif isinstance(main_struct.get(key, None), list) or isinstance(substruct.get(key, None), list):
                    self.logger.dbglow(f" - merge list(s) key='{key}', value='{substruct[key]}' -> new_struct='{dict(main_struct)}'")
                    main_struct[key] = self.merge_structlists(main_struct[key], substruct[key], key)
                else:
                    self.logger.dbglow(f" - key='{key}', value '{substruct[key]}' is ignored'")

        return


    def merge_structlists(self, l1, l2, key=''):
        # if not self.struct_merge_lists:
        #     self.logger.warning(f"merge_structlists: Not merging lists, key '{key}' value '{l2}' is ignored'")
        #     return l1       # First wins
        # else:
        if not isinstance(l1, list):
            l1 = [l1]
        if not isinstance(l2, list):
            l2 = [l2]
        return l1 + l2


    def merge(self, source, destination, source_name='', dest_name=''):
        '''
        Merges an OrderedDict Tree into another one

        :param source: source tree to merge into another one
        :param destination: destination tree to merge into
        :type source: OrderedDict
        :type destination: OrderedDict

        :return: Merged configuration tree
        :rtype: OrderedDict

        :Example: Run me with nosetests --with-doctest file.py

        .. code-block:: python

            >>> a = { 'first' : { 'all_rows' : { 'pass' : 'dog', 'number' : '1' } } }
            >>> b = { 'first' : { 'all_rows' : { 'fail' : 'cat', 'number' : '5' } } }
            >>> merge(b, a) == { 'first' : { 'all_rows' : { 'pass' : 'dog', 'fail' : 'cat', 'number' : '5' } } }
            True

        '''
        # self.logger.warning("merge: source_name='{}', dest_name='{}'".format(source_name, dest_name))
        for key, value in source.items():
            if key == "__struct_is_optional":
                continue
            if isinstance(value, collections.OrderedDict):
                # get node or create one
                node = destination.setdefault(key, collections.OrderedDict())
                if node == 'None':
                    destination[key] = value
                else:
                    self.merge(value, node, source_name, dest_name)
            else:
                if isinstance(value, list) or isinstance(destination.get(key, None), list):
                    if destination.get(key, None) is None:
                        destination[key] = value
                    else:
                        destination[key] = self.merge_structlists(destination[key], value, key)
                else:
                    # convert to string and remove newlines from multiline attributes
                    if destination.get(key, None) is None:
                        destination[key] = str(value).replace('\n', '')
        return destination
