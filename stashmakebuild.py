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

""" Safebuild is capable of doing backup and restore of workspace.
This ensures that package repository gets incremental updates and only
minimal set of packages are created """

import argparse
import logging
import os
import re
import subprocess
import tarfile

from rpmbuilder.log import configure_logging
from makebuild import Build, BuildingError, ArgumentMakebuild
from stashworkspace import ArgumentRemote, Stasher


class Safebuild(Build):

    """ Safebuild extends capabilities of Build by providing backup and
    restore on top of normal building activities """

    def __init__(self, args):
        super(Safebuild, self).__init__(args)
        self.logger = logging.getLogger(__name__)
        self.args = args

        self.backupfilename = "configuration.tar.gz"
        self.remotehost = args.remotehost
        self.remotedir = args.remotedir

    def start_safebuilding(self):
        """ Starting a build requires checking of workspace, doing build
        and then backing up the state of build system """
        self.logger.info("Starting safe building by using remote %s:%s",
                         self.remotehost, self.remotedir)
        self.prepare_workspace()
        self.update_building_blocks()
        if self.start_building():
            self.backup_workspace()
            if self.args.remotefunction == "pullpush":
                stasher = Stasher()
                stasher.push_workspace_to_remote(toserver=self.remotehost,
                                                 todirectory=self.remotedir,
                                                 workspace=self.args.workspace)
            else:
                self.logger.info("Skipping updating remote host with new packages")

    def tar_file_from_workspace(self, tar, sourcefile):
        """ Archiving file from under workspace without
        workspace parent directory structure """
        arcfile = os.path.join(self.args.workspace, sourcefile)
        # Remove workspace directory from file
        arcnamestring = re.sub(self.args.workspace, '', arcfile)
        self.logger.debug("Archiving %s", arcfile)
        tar.add(arcfile, arcname=arcnamestring)

    def backup_workspace(self):
        """ Backup status files and repositories """
        backuptarfile = os.path.join(self.args.workspace, self.backupfilename)
        self.logger.debug("Creating backup of configuration: %s",
                          backuptarfile)
        with tarfile.open(backuptarfile, 'w:gz') as tar:
            # Project settings
            projdir = os.path.join(self.args.workspace, "projects")
            for occurence in os.listdir(projdir):
                statusfile = os.path.join(projdir, occurence, 'status.txt')
                self.logger.info("Backing up file: %s", statusfile)
                if os.path.isfile(statusfile):
                    self.tar_file_from_workspace(tar, statusfile)
                else:
                    self.logger.warning("No %s for archiving", statusfile)

    def prepare_workspace(self):
        """ Check that workspace contains correct beginning state """
        projectsdir = os.path.join(self.args.workspace, "projects")
        if os.path.isdir(projectsdir):
            self.logger.info("Using existing Workspace %s", self.args.workspace)
        else:
            self.logger.info("Trying to restore workspace from remote")
            self.restore_workspace_from_remote(self.remotehost, self.remotedir)

    def restore_workspace_from_remote(self, fromserver, fromdirectory):
        """ Retrieve and restore workspace from remote server """
        self.logger.info("Restoring workspace from remote %s:%s", fromserver, fromdirectory)
        source = fromserver + ":" + fromdirectory
        sshoptions = 'ssh -o stricthostkeychecking=no -o userknownhostsfile=/dev/null -o batchmode=yes -o passwordauthentication=no'
        cmd = ["/usr/bin/rsync",
               "--archive",
               "-e", sshoptions,
               os.path.join(source, "buildrepository"),
               os.path.join(source, self.backupfilename),
               os.path.join(self.args.workspace)]
        self.logger.debug("Running: %s", str(cmd))
        try:
            subprocess.check_call(cmd, shell=False, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as err:
            if err.returncode == 23:
                self.logger.info("There is no remote backup.. doing initial build")
                return True
            else:
                raise BuildingError("Rsync from remote server failed with exit code %d" % err.returncode)
        except:
            raise BuildingError("Unexpected error")

        backupfile = os.path.join(self.args.workspace, self.backupfilename)
        with tarfile.open(backupfile, 'r:gz') as tar:
            tar.extractall(path=self.args.workspace)
        self.logger.info("Workspace restored from %s:%s",
                         fromserver,
                         fromdirectory)


class ArgumentStashMakebuild(object):
    """ Default arguments which are always needed """
    def __init__(self):
        """ init """
        self.parser = argparse.ArgumentParser(description='''
            RPM building tool for continuous integration and development usage.
            Uses remote host to retrieve and store incremental building state.
        ''')
        ArgumentMakebuild().set_arguments(self.parser)
        ArgumentRemote().set_arguments(self.parser)
        self.parser.add_argument("--remotefunction",
                                 choices=["pull", "pullpush"],
                                 default="pull",
                                 help="With \"pullpush\" remote is used to fetch previous"
                                 " build state and on succesful build remote  is updated with"
                                 " new packages. With \"pull\" packages are fetched but "
                                 " remote is not updated on succesful builds. (Default: pull)")


def main():
    """ Read arguments and start processing build configuration """
    args = ArgumentStashMakebuild().parser.parse_args()

    debugfiletarget = os.path.join(args.workspace, 'debug.log')
    configure_logging(args.verbose, debugfiletarget)
    building = Safebuild(args)
    building.start_safebuilding()


if __name__ == "__main__":
    main()
