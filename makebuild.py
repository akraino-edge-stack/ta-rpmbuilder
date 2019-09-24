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

"""
This module loops through user given configuration and creates
projects based on that information. Projects are then build
"""
import argparse
import logging
import os
import platform
import re
import shutil
import sys

from rpmbuilder.baseerror import RpmbuilderError
from rpmbuilder.buildhistory import Buildhistory
from rpmbuilder.configfile import Configfilereader
from rpmbuilder.log import configure_logging
from rpmbuilder.mockbuilder import GitMockbuilder, LocalMockbuilder
from rpmbuilder.packagebuilding import Packagebuilding
from rpmbuilder.project import GitProject, LocalMountProject
from rpmbuilder.prettyprinter import Prettyprint
from rpmbuilder.rpmtools import Repotool
from rpmbuilder.utils import find_files


class Build(object):

    """
    Build configuration module which creates projects and does building
    """

    def __init__(self, args):
        self.logger = logging.getLogger(__name__)
        self.workspace = os.path.abspath(args.workspace)
        if hasattr(args, 'buildconfig') and args.buildconfig:
            self.configuration = Configfilereader(os.path.abspath(args.buildconfig))
        self.builder = None
        self.projects = {}
        self.args = args
        self.packagebuilder = Packagebuilding(args)

    def update_building_blocks(self):
        """ Update version control system components and project configuration """
        # Mock building tools
        Prettyprint().print_heading("Initialize builders", 80)
        default_conf_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'defaults/lcc-epel-7-x86_64.cfg')
        if hasattr(self.args, 'mockconf') and self.args.mockconf:
            self.logger.debug("Loading Mock builder from local disk")
            self.builder = LocalMockbuilder(self.args.mockconf)
        elif hasattr(self, 'configuration') and self.configuration:
            self.logger.debug("Loading Mock builder from Git")
            self.builder = GitMockbuilder(self.workspace, self.configuration)
            if self.builder.check_builder_changed():
                self.args.forcerebuild = True
        elif os.path.isfile(default_conf_file):
            self.logger.debug("Loading default Mock configuration from %s file", default_conf_file)
            self.builder = LocalMockbuilder(default_conf_file)
        else:
            self.logger.critical("No Mock builder configured. Define one in build config file or provide it with -m option.")
            raise BuildingError("No Mock builder configured.")

        # Projects outside of project configuration
        if hasattr(self.args, 'localproj') and self.args.localproj:
            self.update_local_mount_projects()

        # Projects from build configuration file
        if hasattr(self, 'configuration') and self.configuration:
            self.update_configini_projects()

        if not self.projects:
            raise BuildingError("No projects defined. Nothing to build.")

    def update_local_mount_projects(self):
        """ Create project objects and initialize project configuration.
        Project has been defined as argument """

        Prettyprint().print_heading("Initialize local projects", 80)
        for projectdir in self.args.localproj:
            if not os.path.isdir(projectdir):
                raise BuildingError("Given \"%s\" is not a directory" % projectdir)
            project_specs = list(find_files(os.path.abspath(projectdir), r'.*\.spec$'))
            for spec in project_specs:
                projectname = os.path.basename(projectdir.rstrip('/'))
                if len(list(project_specs)) > 1:
                    projectname = projectname + '_' + os.path.splitext(os.path.basename(spec))[0]
                self.projects[projectname] = LocalMountProject(projectname,
                                                           os.path.abspath(projectdir),
                                                           self.workspace,
                                                           self.projects,
                                                           self.builder,
                                                           self.packagebuilder,
                                                           self.args,
                                                           spec_path=spec)

    def update_configini_projects(self):
        """ Create project objects and initialize project configuration.
        Project has been defined in configuration file """
        Prettyprint().print_heading("Initialize projects", 80)
        for section in self.configuration.get_sections():
            if self.configuration.get_string(section, "type") == "project" \
                    and self.configuration.get_bool(section, "enabled", defaultvalue=True):
                if section in self.projects:
                    self.logger.warning("Local %s project already configured. Skipping build config entry", section)
                else:
                    self.projects[section] = GitProject(section,
                                                        self.workspace,
                                                        self.configuration,
                                                        self.projects,
                                                        self.builder,
                                                        self.packagebuilder,
                                                        self.args)

    def start_building(self):
        """ search for changes and start building """
        Prettyprint().print_heading("Summary of changes", 80)
        projects_to_build = self.get_projects_to_build()
        self.logger.debug("Final list of projects to build: %s",
                          str(projects_to_build))

        Prettyprint().print_heading("Projects to build", 80)
        if projects_to_build:
            self.logger.info("%-30s %10s %10s", "Name", "Changed", "Rebuild")
            for project in projects_to_build:
                req_by = ""
                if self.projects[project].buildrequires_upstream:
                    req_by = "(build requires: {})".format(
                        ', '.join(self.projects[project].buildrequires_upstream))
                self.logger.info("%-30s %10s %10s    %s",
                                 self.projects[project].name,
                                 self.projects[project].project_changed,
                                 self.projects[project].project_rebuild_needed,
                                 req_by)

            Prettyprint().print_heading("Building projects", 80)

            if self.mock_projects(projects_to_build):
                self.logger.info("All built succesfully..")
                Prettyprint().print_heading("Running final steps", 80)
                self.finalize(projects_to_build)

                # Clean mock chroot
                for mockroot in self.builder.roots:
                    if self.args.scrub:
                        self.packagebuilder.scrub_mock_chroot(self.builder.get_configdir(),
                                                              mockroot)
                return True
            else:
                self.logger.critical("Problems while building")
                raise BuildingError("Error during rpm mock")
        else:
            self.logger.info("No projects to build.. no changes")
        return None

    def get_projects_to_build(self):
        """ Find which project are not built yet """
        buildlist = []
        # Find projects that need to be build because of change
        for project in self.projects:
            if self.projects[project].project_changed \
                    or self.projects[project].project_rebuild_needed:
                self.logger.info("Project \"%s\": Need to build", project)
                buildlist.append(project)
            else:
                self.logger.info("Project \"%s\": OK. Already built", project)

        # Find projects that have list changed projects in buildrequires
        if buildlist:
            self.logger.debug("Projects %s need building.", str(buildlist))
            self.logger.debug("Looking for projects that need rebuild")
            projects_to_rebuild = []
            for project in buildlist:
                self.logger.debug("Project \"%s\" need building.", project)
                self.logger.debug("Checking if downstream requires rebuilding")
                need_rebuild = \
                    self.projects[
                        project].mark_downstream_for_rebuild(set(buildlist))
                self.logger.debug("Rebuild needed for: %s", str(need_rebuild))
                projects_to_rebuild.extend(need_rebuild)
            buildlist.extend(projects_to_rebuild)
        buildlist = list(set(buildlist))
        buildlist.sort()
        return buildlist

    def mock_projects(self, build_list):
        """ Loop through all mock chroots to build projects """
        for mockroot in self.builder.roots:
            Prettyprint().print_heading("Processing chroot " + mockroot, 70)
            if self.args.init:
                # Create mock chroot for project building
                self.packagebuilder.init_mock_chroot(os.path.join(self.workspace, "mocksettings", "logs"),
                                                     self.builder.get_configdir(),
                                                     mockroot)
            # Restore local yum repository to Mock environment
            hostyumrepository = os.path.join(self.workspace, "buildrepository", mockroot, "rpm")
            if os.path.isdir(os.path.join(hostyumrepository, "repodata")):
                logfile = os.path.join(self.workspace, 'restore-mock-env-yum-repository.log')
                self.packagebuilder.restore_local_repository(hostyumrepository,
                                                             "/usr/localrepo",
                                                             self.builder.get_configdir(),
                                                             mockroot,
                                                             logfile=logfile)

            # Mock projects
            if not self.build_projects(build_list, mockroot):
                return False
        return True

    def upstream_packages_in_buildlist(self, project, buildlist):
        for proj in self.projects[project].buildrequires_upstream:
            if proj in buildlist:
                return True
        return False

    def build_projects(self, build_list, mockroot):
        """ Build listed projects """
        self.logger.debug("%s: Projects to build=%s",
                          mockroot,
                          str(build_list))
        self.packagebuilder.update_local_repository(self.builder.get_configdir(), mockroot)
        something_was_built = True
        while something_was_built:
            something_was_built = False
            not_built = []
            for project in build_list:
                self.logger.debug("Trying to build: {}".format(project))
                self.logger.debug("Build list: {}".format(build_list))
                if not self.upstream_packages_in_buildlist(project, build_list):
                    if not self.projects[project].resolve_dependencies(mockroot):
                        self.logger.info("still unresolved dependencies: {}".format(project))
                        not_built.append(project)
                    else:
                        self.logger.debug("OK to build {}".format(project))
                        self.projects[project].build_project(mockroot)
                        something_was_built = True
                        self.packagebuilder.update_local_repository(self.builder.get_configdir(), mockroot)
                else:
                    self.logger.debug("Skipping {} because upstream is not built yet".format(project))
                    not_built.append(project)
            build_list = not_built

        if build_list:
            self.logger.warning("Requirements not available for \"%s\"",
                                ", ".join(build_list))
            return False
        return True

    def finalize(self, projectlist):
        """ Do final work such as create yum repositories """
        commonrepo = os.path.join(self.workspace, 'buildrepository')
        self.logger.info("Hard linking rpm packages to %s", commonrepo)
        for project in projectlist:
            self.projects[project].store_build_products(commonrepo)

        for mockroot in self.builder.roots:
            Repotool().createrepo(os.path.join(self.workspace,
                                               'buildrepository',
                                               mockroot,
                                               'rpm'))
            Repotool().createrepo(os.path.join(self.workspace,
                                               'buildrepository',
                                               mockroot,
                                               'srpm'))
        # Store information of used builder
        # Next run then knows what was used in previous build
        self.builder.store_builder_status()

        buildhistory = Buildhistory()
        historyfile = os.path.join(commonrepo, "buildhistory")
        buildhistory.update_history(historyfile,
                                    projectlist,
                                    self.projects)
        return True

    def rm_obsolete_projectdirs(self):
        """ Clean projects which are not listed in configuration """
        self.logger.debug("Cleaning unused project directories")
        projects_directory = os.path.join(self.workspace, 'projects')
        if not os.path.isdir(projects_directory):
            return True
        for subdir in os.listdir(projects_directory):
            fulldir = os.path.join(projects_directory, subdir)
            if subdir in self.projects:
                self.logger.debug("Project directory %s is active",
                                  fulldir)
            else:
                self.logger.debug("Removing directory %s. No match in projects",
                                  fulldir)
                shutil.rmtree(fulldir)
        return True


class BuildingError(RpmbuilderError):
    """ Exceptions originating from builder """
    pass


def warn_if_incompatible_distro():
    if platform.linux_distribution()[0].lower() not in ['fedora', 'redhat', 'rhel', 'centos']:
        logger = logging.getLogger()
        logger.warning("Distribution compatibility check failed.\n"
                       "If you use other than Fedora, RedHat or CentOS based Linux distribution, you might experience problems\n"
                       "in case there are BuildRequirements between your own packages. For more information, read README.md")


class ArgumentMakebuild(object):
    """ Default arguments which are always needed """

    def __init__(self):
        """ init """
        self.parser = argparse.ArgumentParser(description='''
            RPM building tool for continuous integration and development usage.
        ''')
        self.set_arguments(self.parser)

    def set_arguments(self, parser):
        """ Add relevant arguments """
        parser.add_argument("localproj",
                            metavar="dir",
                            help="Local project directory outside of buildconfig. This option can be used multiple times.",
                            nargs="*")
        parser.add_argument("-w",
                            "--workspace",
                            help="Sandbox directory for builder. Used to store repository clones and built rpm files. Required option.",
                            required=True)
#        parser.add_argument("-b",
#                            "--buildconfig",
#                            help="Build configuration file lists projects and mock configuration. Required option.")
        parser.add_argument("-m",
                            "--mockconf",
                            help="Local Mock configuration file. Overrides mock settings from build configuration.")
        parser.add_argument("--mockarguments",
                            help="Arguments to be passed to mock. Check possible arguments from mock man pages")
        parser.add_argument("-v",
                            "--verbose",
                            help="Verbosed printing.",
                            action="store_true")
        parser.add_argument("-f",
                            "--forcerebuild",
                            help="Force rebuilding of all projects.",
                            action="store_true")
        parser.add_argument("--nowipe",
                            help="Skip cleaning of Mock chroot if build fails. "
                            "Old chroot can be used for debugging but if you use this option, then you need to clean unused chroot manually.",
                            action="store_false",
                            dest="scrub")
        parser.add_argument("--nosrpm",
                            help="Skip source rpm creation.",
                            action="store_true")
        parser.add_argument("--noinit",
                            help="Skip initialization (cleaning) of mock chroot.",
                            default=True,
                            action="store_false",
                            dest="init")
        parser.add_argument("--uniqueext",
                            help="Unique extension used for cache.",
                            default=str(os.getpid()),
                            dest="uniqueext")


def main():
    """ Read arguments and start processing build configuration """
    args = ArgumentMakebuild().parser.parse_args()

    debugfiletarget = os.path.join(args.workspace, 'debug.log')
    configure_logging(args.verbose, debugfiletarget)

    warn_if_incompatible_distro()

    # Start the build system
    try:
        build = Build(args)
        build.update_building_blocks()
        build.start_building()
    except RpmbuilderError as err:
        logger = logging.getLogger()
        logger.error("Could not produce a build. %s", err)
        warn_if_incompatible_distro()
        raise

if __name__ == "__main__":
    try:
        main()
    except RpmbuilderError:
        sys.exit(1)
