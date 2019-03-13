# Copyright 2019 Nokia
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Read sections from a build configuration file and check that
all required values have been given.
"""
import ConfigParser
import logging
import re

from rpmbuilder.baseerror import RpmbuilderError


class Configfilereader(object):

    """ Reading and processing of user given configuration file """

    def __init__(self, configfile):
        self.logger = logging.getLogger(__name__)
        self.configfile = configfile
        self.configuration = self.readconfig(configfile)

    def readconfig(self, configfile):
        """ Configuration file reading """
        conf = ConfigParser.ConfigParser()
        try:
            with open(configfile) as filep:
                conf.readfp(filep)
        except IOError:
            raise ConfigError("Failed to open configuration file %s" % configfile)

        self.__validate_section_names(conf)
        return conf

    def get_bool(self, section, option, mandatory=False, defaultvalue=False):
        """ Get boolean values from configuration. In case of problems do raise
        or just return default value """
        try:
            return self.configuration.getboolean(section, option)
        except ConfigParser.NoSectionError:
            raise ConfigError("Could not find required [%s] section in configuration" % section)
        except ConfigParser.NoOptionError:
            if mandatory:
                raise ConfigError("Could not find option %s from [%s] section" % option, section)
            else:
                return defaultvalue
        except:
            raise

    def get_string(self, section, option, mandatory=False, defaultvalue=None):
        """ Return the requested value from the given section. In case of problems
        do raise or just return default value"""
        try:
            return self.configuration.get(section, option)
        except ConfigParser.NoSectionError:
            raise ConfigError("Could not find required [%s] section in configuration" % section)
        except ConfigParser.NoOptionError:
            if mandatory:
                raise ConfigError("Could not find option %s from [%s] section" % option, section)
            else:
                return defaultvalue
        except:
            raise

    def get_sections(self):
        """ List all sections from the configuration """
        try:
            return self.configuration.sections()
        except:
            raise

    def __validate_section_names(self, configuration):
        """ Loop through all section names and do validation """
        for section in configuration.sections():
            self.__validate_section_name(section)

    def __validate_section_name(self, name):
        """ Check that section contains characters that
        do not cause problems for directory names """
        if not re.match('^[A-Za-z0-9-]+$', name):
            self.logger.critical("Configuration of [%s] has problems.", name,
                                 "Section name can has illegal characters"
                                 "Use only alphanumeric and dashes")
            raise ConfigError("Section %s name contains illegal characters" % name)


class ConfigError(RpmbuilderError):

    """ Exception for configuration file content problems """
    pass
