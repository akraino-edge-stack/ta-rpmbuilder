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

""" Handling of mock building environment """
import json
import logging
import os

from rpmbuilder.baseerror import RpmbuilderError
from rpmbuilder.version_control import VersionControlSystem


class Mockbuilder(object):

    """ Mockbuilder handled mock building configuration """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.roots = []


class LocalMockbuilder(Mockbuilder):

    """ Mock configuration contains information of chroot used for building.
    Configuration is taken from local file"""

    def __init__(self, configfile):
        super(LocalMockbuilder, self).__init__()

        self.roots.append(os.path.basename(configfile.rstrip('/').rstrip('.cfg')))
        self.configdir = os.path.dirname(os.path.abspath(configfile))

    def get_configdir(self):
        return self.configdir

    def store_builder_status(self):
        pass


class GitMockbuilder(Mockbuilder):

    """ Mock configuration contains information of chroot used for building.
    Configuration is taken from git"""

    def __init__(self, workspace, conf):
        super(GitMockbuilder, self).__init__()

        self.mock_settings_dir = os.path.join(workspace, "mocksettings")
        self.mock_settings_checkout_dir = os.path.join(self.mock_settings_dir,
                                                       "checkout")

        confsection = "mock"
        self.roots = self.__list_from_csv(conf.get_string(confsection,
                                                          "roots",
                                                          mandatory=True))

        self.vcs = VersionControlSystem(self.mock_settings_checkout_dir)

        try:
            self.vcs.update_git_project(conf.get_string(confsection,
                                                        "url",
                                                        mandatory=True),
                                        conf.get_string(confsection,
                                                        "ref",
                                                        mandatory=True))
        except:
            self.logger.critical("Problems updating git clone")
            raise

    def get_configdir(self):
        return os.path.join(self.mock_settings_checkout_dir, 'etc', 'mock')

    def store_builder_status(self):
        """ Save information of the builder checkout. This way we can
        check if mock configuration has changed and all projects can be
        rebuild """
        statusfile = os.path.join(self.mock_settings_dir, 'status.txt')
        self.logger.debug("Updating %s", statusfile)
        projectstatus = {"sha": self.vcs.commitsha}
        try:
            with open(statusfile, 'w') as outfile:
                json.dump(projectstatus, outfile)
        except:
            self.logger.error("Could not create a status file")
            raise

    def check_builder_changed(self):
        """
        Check if there has been changes in the project
        if project has not been compiled -> return = True
        if project has GIT/VCS changes   -> return = True
        if project has not changed       -> return = False
        """
        statusfile = os.path.join(self.mock_settings_dir, 'status.txt')

        if os.path.isfile(statusfile):
            with open(statusfile, 'r') as filep:
                previousprojectstatus = json.load(filep)
            # Compare old values against new values
            if previousprojectstatus['sha'] != self.vcs.commitsha:
                self.logger.debug("Mock configuration has changed")
                return True
            else:
                self.logger.debug("Mock configuration has NO changes")
            return False
        else:
            # No configuration means that project has not been compiled
            pass
        return True

    @staticmethod
    def __list_from_csv(csv):
        """ Create a list of comma separated value list
        For example foo,bar would be converted to ["foo","bar"] """
        outlist = []
        for entry in set(csv.split(',')):
            outlist.append(entry.strip())
        return outlist


class MockbuilderError(RpmbuilderError):

    """ Exceptions originating from Builder and main level """
    pass
