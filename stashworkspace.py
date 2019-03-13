#! /usr/bin/python -tt
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

import argparse
import os
import subprocess

class Stasher(object):
    def __init__(self, args=None):
        self.args = args
        self.backupfilename = "configuration.tar.gz"

    def start(self):
        self.push_workspace_to_remote(toserver=self.args.remotehost,
                                      todirectory=self.args.remotedir,
                                      workspace=self.args.workspace)

    def push_workspace_to_remote(self, toserver, todirectory, workspace):
        """ Move workspace backup to remote host """
        destination = toserver + ":" + todirectory
        sshoptions = 'ssh -o stricthostkeychecking=no -o userknownhostsfile=/dev/null -o batchmode=yes -o passwordauthentication=no'
        sourceconfiguration = os.path.join(workspace, self.backupfilename)
        sourcerpm = os.path.join(workspace, "buildrepository")
        rsyncpathval = "mkdir -p " + todirectory + " && rsync"
        cmd = ["/usr/bin/rsync",
               "--verbose",
               "--archive",
               "--rsync-path", rsyncpathval,
               "-e", sshoptions,
               sourceconfiguration, sourcerpm,
               destination]
        try:
            print subprocess.check_output(cmd, shell=False, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as err:
            raise StasherError("Following command retured code %d: %s" % (err.returncode,
                                                                          ' '.join(err.cmd)))

class StasherError(Exception):
    """ Exceptions originating from builder """
    pass



class ArgumentRemote(object):
    """ Default arguments which are always needed """
    def __init__(self):
        """ Create parser for arguments """
        self.parser = argparse.ArgumentParser(description='Workspace stasher copies workspace to remote host.')
        self.set_arguments(self.parser)
        self.parser.add_argument("--workspace",
                                 help="Local (source) directory",
                                 required=True)

    def set_arguments(self, parser):
        """ Add extra arguments to parser """
        parser.add_argument("--remotehost",
                            help="Remote host where script will ssh/rsync to store build",
                            required=True)
        parser.add_argument("--remotedir",
                            help="Remote directory to use for storing build",
                            required=True)


def main():
    """ Get arguments required for stashing local workspace """
    args = ArgumentRemote().parser.parse_args()

    stasher = Stasher(args)
    stasher.start()

if __name__ == "__main__":
    main()
