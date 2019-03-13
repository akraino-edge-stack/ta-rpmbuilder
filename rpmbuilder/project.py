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
Project is a subsystem which contains one spec file which
defines how it is build. Every project has one git
repository from where it is cloned from.
"""
import glob
import json
import logging
import os
import shutil
import subprocess

import re

import datetime
from rpmbuilder.baseerror import RpmbuilderError
from rpmbuilder.prettyprinter import Prettyprint
from rpmbuilder.rpmtools import Repotool, Specworker, RepotoolError, SpecError
from rpmbuilder.utils import find_files
from rpmbuilder.version_control import VersionControlSystem, VcsError
from rpmbuilder.get_sources import get_sources


class Project(object):

    """ Instance of a project """

    def __init__(self, name, workspace, projects, builders, packagebuilder, chrootscrub=True, nosrpm=False):
        self.name = name

        self.logger = logging.getLogger(__name__ + "." + self.name)

        self.project_rebuild_needed = False

        self.project_workspace = os.path.join(workspace,
                                              'projects',
                                              self.name)

        self.projects = projects
        self.builders = builders
        self.directory_of_specpatch = os.path.join(self.project_workspace,
                                                   'rpmbuild',
                                                   'spec')
        self.directory_of_sourcepackage = os.path.join(self.project_workspace,
                                                       'rpmbuild',
                                                       'sources')
        self.directory_of_srpms = os.path.join(self.project_workspace,
                                               'rpmbuild',
                                               'srpm')
        self.directory_of_rpm = os.path.join(self.project_workspace,
                                             'rpmbuild',
                                             'rpm')
        self.directory_of_commonrepo = os.path.join(workspace,
                                                    'buildrepository')

        self.directory_of_builder = self.builders.get_configdir()

        self.__create_directories([self.directory_of_specpatch,
                                   self.directory_of_srpms],
                                  verify_empty=True)
        self.__create_directories([self.directory_of_sourcepackage],
                                  verify_empty=False)

        self.packagebuilder = packagebuilder

        self.chrootscrub = chrootscrub
        self.built = {}
        for mockroot in builders.roots:
            self.built[mockroot] = False

        self.project_changed = False
        self.projconf = None
        self.spec = None
        self.useversion = None
        self.directory_of_checkout = None
        self.nosrpm = nosrpm
        self.centos_style = False
        self.buildrequires_downstream = set()
        self.buildrequires_upstream = set()

    def mark_for_rebuild(self):
        """ Marking project for rebuild only if project has not changed """
        if not self.project_changed:
            self.logger.debug("Marking project %s for rebuild.", self.name)
            self.project_rebuild_needed = True

    def mark_downstream_for_rebuild(self, marked_for_build=None):
        """
        Recursively mark downstream projects for rebuilding.
        Return set of projects marked for rebuild
        """
        if marked_for_build is None:
            marked_for_build = set()
        self.logger.debug("Marking downstream for rebuild in \"%s\"",
            self.name)
        for project in self.who_buildrequires_me():
            self.logger.debug("BuildRequires to \"%s\" found in \"%s\"",
                self.name, project)
            if project in marked_for_build:
                self.logger.debug("\"%s\" already marked for build", project)
            elif self.projects[project].project_rebuild_needed:
                self.logger.debug("\"%s\" already marked for rebuild", project)
            else:
                self.projects[project].mark_for_rebuild()
                marked_for_build.add(project)
                # Check if downstream has downstream projects
                tmpset = self.projects[project].mark_downstream_for_rebuild(
                    marked_for_build)
                marked_for_build.update(tmpset)
        return marked_for_build

    def build_project(self, mockroot):
        """ Do building of SRPM and RPM files """
        time_start = datetime.datetime.now()
        Prettyprint().print_heading("Build " + self.name, 60)
        assert not self.built[mockroot], "Project already built"

        # Produce spec file
        if self.spec.version == '%{_version}':
            self.logger.debug("patching spec file")
            self.logger.debug("Version in spec is going to be %s", self.useversion)

            rpm = Repotool()
            userelease = rpm.next_release_of_package(
                os.path.join(self.directory_of_commonrepo,
                             self.builders.roots[0],
                             "rpm"),
                self.spec.name,
                self.useversion,
                self.spec.release)
            self.logger.debug("Release in spec is going to be %s", userelease)

            specfile = self.packagebuilder.patch_specfile(self.spec.specfilefullpath,
                                                          self.directory_of_specpatch,
                                                          self.useversion,
                                                          userelease)
        else:
            self.logger.debug("Skipping spec patching")
            specfile = self.spec.specfilefullpath

        # Start mocking
        self.logger.debug("Starting building in root \"%s\"", mockroot)
        if self.centos_style:
            shutil.rmtree(self.directory_of_sourcepackage)
            ignore_git = shutil.ignore_patterns('.git')
            shutil.copytree(self.directory_of_checkout, self.directory_of_sourcepackage, ignore=ignore_git)
            sources_key = 'CENTOS_SOURCES'
            if sources_key not in os.environ:
                raise RpmbuilderError('Cannot build CentOS style RPM, %s not defined in the environment' % sources_key)
            get_sources(self.directory_of_sourcepackage, os.environ[sources_key].split(','), self.logger)
            self.create_rpm_from_filesystem(self.directory_of_sourcepackage, mockroot)
        elif self.nosrpm:
            list_of_source_packages = self.get_source_package()
            self.create_rpm_from_archive(list_of_source_packages, mockroot)
        else:
            self.get_source_package()
            # Create source RPM file
            sourcerpm = self.get_source_rpm(self.directory_of_sourcepackage, specfile, mockroot)

            # Create final RPM file(s)
            self.create_rpm_from_srpm(sourcerpm, mockroot)

        # Mark build completed
        self.built[mockroot] = True
        time_delta = datetime.datetime.now() - time_start
        self.logger.info('Building success: %s (took %s [%s sec])', self.name, time_delta, time_delta.seconds)

        # We wipe buildroot of previously built rpm, source etc. packages
        # This is custom cleaning which does not remove chroot
        self.packagebuilder.mock_wipe_buildroot(self.project_workspace, self.directory_of_builder, mockroot)

    def pull_source_packages(self, target_dir):
        cmd = ['/usr/bin/spectool', '-d', 'KVERSION a.b', '-g', '--directory', target_dir, self.spec.specfilefullpath]
        self.logger.info('Pulling source packages: %s', cmd)
        try:
            subprocess.check_call(cmd, shell=False)
            self.logger.info('Pulling source packages ok')
        except OSError as err:
            self.logger.info('Pulling source packages nok %s', err.strerror)
            raise RepotoolError("Calling of command spectool caused: \"%s\"" % err.strerror)
        except:
            self.logger.info('Pulling source packages nok ??', err.strerror)
            raise RepotoolError("There was error pulling source content")

    def get_source_package(self):
        # Produce source package
        source_package_list = []
        for source_file_hit in self.spec.source_files:
            self.logger.info("Acquiring source file \"%s\"", source_file_hit)
            if re.match(r'^(http[s]*|ftp)://', source_file_hit):
                self.logger.info("PULL %s", self.directory_of_sourcepackage)
                self.pull_source_packages(self.directory_of_sourcepackage)
                source_package_list.append(self.directory_of_sourcepackage + '/' + source_file_hit.split('/')[-1])
                continue
            for subdir in ["", "SOURCES"]:
                if os.path.isfile(os.path.join(self.directory_of_checkout, subdir, source_file_hit)):
                    shutil.copy(os.path.join(self.directory_of_checkout, subdir, source_file_hit), self.directory_of_sourcepackage)
                    source_package_list.append(os.path.join(self.directory_of_sourcepackage, source_file_hit))
                    break
            else:
                tarname = self.spec.name + '-' + self.useversion
                source_package_list.append(self.packagebuilder.create_source_archive(tarname,
                                                                                     self.directory_of_checkout,
                                                                                     self.directory_of_sourcepackage,
                                                                                     self.project_changed,
                                                                                     self.spec.source_file_extension))

        for patch_file_hit in self.spec.patch_files:
            self.logger.info("Copying %s to directory %s", patch_file_hit, self.directory_of_sourcepackage)
            for subdir in ["", "SOURCES"]:
                if os.path.isfile(os.path.join(self.directory_of_checkout, subdir, patch_file_hit)):
                    shutil.copy(os.path.join(self.directory_of_checkout, subdir, patch_file_hit), self.directory_of_sourcepackage)
                    break
            else:
                raise ProjectError("Spec file lists patch \"%s\" but no file found" % patch_file_hit)
        return source_package_list


    def get_source_rpm(self, hostsourcedir, specfile, mockroot):
        return self.packagebuilder.mock_source_rpm(hostsourcedir,
                                                   specfile,
                                                   self.directory_of_srpms,
                                                   self.directory_of_builder,
                                                   mockroot)

    def create_rpm_from_srpm(self, sourcerpm, mockroot):
        directory_of_rpm = os.path.join(self.directory_of_rpm, mockroot)
        self.packagebuilder.mock_rpm(sourcerpm,
                                     directory_of_rpm,
                                     self.directory_of_builder,
                                     mockroot)
        # Delete duplicated src.rpm which is returned by rpm creation
        os.remove(os.path.join(directory_of_rpm, os.path.basename(sourcerpm)))

    def create_rpm_from_archive(self, source_tar_packages, mockroot):
        directory_of_rpm = os.path.join(self.directory_of_rpm, mockroot)
        self.packagebuilder.mock_rpm_from_archive(source_tar_packages, directory_of_rpm, self.directory_of_builder, mockroot)

    def create_rpm_from_filesystem(self, path, mockroot):
        directory_of_rpm = os.path.join(self.directory_of_rpm, mockroot)
        self.packagebuilder.mock_rpm_from_filesystem(path,
                                                     self.spec.specfilename,
                                                     directory_of_rpm,
                                                     self.directory_of_builder,
                                                     mockroot,
                                                     self.directory_of_srpms)

    def list_buildproducts_for_mockroot(self, mockroot):
        """ List both source and final rpm packages """
        srpmlist = []
        rpmlist = []
        for occurence in os.listdir(os.path.join(self.directory_of_rpm, mockroot)):
            if occurence.endswith(".rpm"):
                rpmlist.append(occurence)
        for occurence in os.listdir(self.directory_of_srpms):
            if occurence.endswith(".src.rpm"):
                srpmlist.append(occurence)
        return rpmlist, srpmlist

    def resolve_dependencies(self, mockroot):
        return self.packagebuilder.run_builddep(self.spec.specfilefullpath,
                                                self.directory_of_srpms,
                                                self.directory_of_builder,
                                                mockroot)

    def store_build_products(self, commonrepo):
        """ Save build products under common yum repository """
        self.__create_directories([commonrepo])
        for mockroot in self.builders.roots:
            srpmtargetdir = os.path.join(commonrepo, mockroot, 'srpm')
            rpmtargetdir = os.path.join(commonrepo, mockroot, 'rpm')
            self.__create_directories([srpmtargetdir, rpmtargetdir])
            (rpmlist, srpmlist) = self.list_buildproducts_for_mockroot(mockroot)
            build_product_dir = os.path.join(self.directory_of_rpm, mockroot)
            self.logger.debug("Hard linking %s rpm packages to %s", self.name, rpmtargetdir)
            for rpm_file in rpmlist:
                self.logger.info("Hard linking %s", rpm_file)
                try:
                    os.link(os.path.join(build_product_dir, rpm_file),
                            os.path.join(rpmtargetdir, os.path.basename(rpm_file)))
                except OSError:
                    pass
            self.logger.debug("Hard linking %s srpm packages to %s", self.name, srpmtargetdir)
            for srpm_file in srpmlist:
                self.logger.info("Hard linking %s", srpm_file)
                try:
                    os.link(os.path.join(self.directory_of_srpms, srpm_file),
                            os.path.join(srpmtargetdir, srpm_file))
                except OSError:
                    pass

        # Store info of latest build
        self.store_project_status()


    def who_buildrequires_me(self):
        """
        Return a list of projects which directly buildrequires this project (non-recursive)
        """
        downstream_projects = set()
        # Loop through my packages
        for package in self.spec.packages:
            # Loop other projects and check if they need me
            # To need me, they have my package in buildrequires
            for project in self.projects:
                if package in self.projects[project].spec.buildrequires:
                    self.logger.debug("Found dependency in {}: my package {} is required by project {}".format(self.name, package, project))
                    self.projects[project].buildrequires_upstream.add(self.name)
                    self.projects[self.name].buildrequires_downstream.add(project)
                    downstream_projects.add(project)
        return downstream_projects


    def who_requires_me(self, recursive=False, depth=0):
        """
        Return a list of projects which have requirement to this project
        """
        if depth > 10:
            self.logger.warn("Hit infinite recursion limiter in {}".format(self.name))
            recursive = False
        # Loop through my packages
        downstream_projects = set()
        for package in self.spec.packages:
            # Loop other projects and check if they need me
            # To need me, they have my package in buildrequires or requires
            for project in self.projects:
                if package in self.projects[project].spec.buildrequires \
                or package in self.projects[project].spec.requires:
                    downstream_projects.add(project)
                    if recursive:
                        downstream_projects.update(
                            self.projects[project].who_requires_me(True, depth+1))
        self.logger.debug("Returning who_requires_me for %s: %s",
            self.name, ', '.join(downstream_projects))
        return downstream_projects

    def get_project_changed(self):
        raise NotImplementedError

    def store_project_status(self):
        raise NotImplementedError

    def __create_directories(self, directories, verify_empty=False):
        """ Directory creation """
        for directory in directories:
            if os.path.isdir(directory):
                if verify_empty and os.listdir(directory) != []:
                    self.logger.debug("Cleaning directory %s", directory)
                    globstring = directory + "/*"
                    files = glob.glob(globstring)
                    for foundfile in files:
                        self.logger.debug("Removing file %s", foundfile)
                        os.remove(foundfile)
            else:
                self.logger.debug("Creating directory %s", directory)
                try:
                    os.makedirs(directory)
                except OSError:
                    raise
        return True

class LocalMountProject(Project):
    """ Projects coming from local disk mount """
    def __init__(self, name, directory, workspace, projects, builders, packagebuilder, masterargs, spec_path):
        chrootscrub = masterargs.scrub
        nosrpm = masterargs.nosrpm
        forcebuild = masterargs.forcerebuild

        Prettyprint().print_heading("Initializing %s from disk" % name, 60)
        super(LocalMountProject, self).__init__(name, workspace, projects, builders, packagebuilder)

        if not os.path.isdir(directory):
            raise ProjectError("No directory %s found", directory)

        self.vcs = VersionControlSystem(directory)
        self.directory_of_checkout = directory

        # Values from build configuration file
        self.projconf = {}
        # Read spec
        if len(list(find_files(directory, r'\..+\.metadata$'))) > 0 and \
                os.path.isdir(os.path.join(directory, 'SOURCES')) and \
                os.path.isdir(os.path.join(directory, 'SPECS')):
            self.centos_style = True
            self.logger.debug('CentOS stype RPM detected')
        self.spec = Specworker(os.path.dirname(spec_path), os.path.basename(spec_path))

        self.gitversioned = False
        try:
            citag = self.vcs.get_citag()
            self.gitversioned = True
        except VcsError:
            self.logger.debug("Project does not come from Git")
        except:
            raise

        if self.spec.version == '%{_version}':
            if self.gitversioned:
                self.logger.debug("Using Git describe for package version")
                self.useversion = citag
            else:
                self.logger.debug("Project not from Git. Using a.b package version")
                self.useversion = 'a.b'
        else:
            self.logger.debug("Using spec definition for package version")
            self.useversion = self.spec.version

        self.packageversion = self.useversion
        self.project_changed = self.get_project_changed()
        self.nosrpm = nosrpm

        if forcebuild:
            self.mark_for_rebuild()

        self.chrootscrub = chrootscrub

    def get_project_changed(self):
        """
        Project status is read from status.txt file. Dirty git clones always require rebuild.
        """
        statusfile = os.path.join(self.project_workspace, 'status.txt')

        if os.path.isfile(statusfile):
            with open(statusfile, 'r') as filep:
                previousprojectstatus = json.load(filep)
            # Compare old values against new values
            if not self.gitversioned:
                self.logger.warning("Project %s is not git versioned. Forcing rebuild.", self.name)
                return True
            elif self.vcs.is_dirty():
                self.logger.warning("Project %s contains unversioned changes and is \"dirty\". Forcing rebuild.", self.name)
                return True
            elif previousprojectstatus['sha'] != self.vcs.commitsha:
                self.logger.info("Project %s log has new hash. Rebuild needed.", self.name)
                return True
            else:
                self.logger.info("Project %s has NO new changes.", self.name)
            return False
        else:
            # No configuration means that project has not been compiled
            self.logger.warning("No previous build found for %s. Building initial version.", self.name)
        return True

    def store_project_status(self):
        """ Write information of project version to status.txt
        This can only be done for git versioned projects """
        if self.gitversioned:
            # Save information of the last compilation
            statusfile = os.path.join(self.project_workspace, 'status.txt')
            self.logger.debug("Updating status file %s", statusfile)

            projectstatus = {"packageversion": self.packageversion,
                             "sha": self.vcs.commitsha,
                             "project": self.name}

            with open(statusfile, 'w') as outfile:
                json.dump(projectstatus, outfile)

class GitProject(Project):
    """ Projects cloned from Git version control system """
    def __init__(self, name, workspace, conf, projects, builders, packagebuilder, masterargs):
        forcebuild = masterargs.forcerebuild
        chrootscrub = masterargs.scrub

        Prettyprint().print_heading("Initializing %s from Git" % name, 60)
        super(GitProject, self).__init__(name, workspace, projects, builders, packagebuilder)

        # Values from build configuration file
        self.projconf = {'url': conf.get_string(name, "url", mandatory=True),
                         'ref': conf.get_string(name, "ref", mandatory=True),
                         'spec': conf.get_string(name, "spec", mandatory=False, defaultvalue=None)}

        # Do version control updates
        self.directory_of_checkout = os.path.join(self.project_workspace,
                                                  'checkout')
        self.vcs = VersionControlSystem(self.directory_of_checkout)
        self.vcs.update_git_project(self.projconf["url"], self.projconf["ref"])
        self.useversion = self.vcs.get_citag()

        # Read spec
        try:
            self.spec = Specworker(self.directory_of_checkout,
                                   self.projconf["spec"])
        except SpecError:
            self.spec = Specworker(os.path.join(self.directory_of_checkout, "SPEC"), None)
            self.centos_style = True

        # Define what version shall be used in spec file
        if self.spec.version == '%{_version}':
            self.packageversion = self.vcs.get_citag()
            self.logger.debug("Taking package version from VCS")
        else:
            self.packageversion = self.spec.version
            self.logger.debug("Taking package version from spec")
        self.logger.debug("Package version: %s", self.packageversion)

        self.project_changed = self.get_project_changed()
        if forcebuild:
            self.mark_for_rebuild()

        self.chrootscrub = chrootscrub

    def get_project_changed(self):
        """
        Check if there has been changes in the project
        if project has not been compiled -> return = True
        if project has GIT/VCS changes   -> return = True
        if project has not changed       -> return = False
        """
        statusfile = os.path.join(self.project_workspace, 'status.txt')

        if os.path.isfile(statusfile):
            with open(statusfile, 'r') as filep:
                previousprojectstatus = json.load(filep)
            # Compare old values against new values
            if previousprojectstatus['url'] != self.projconf["url"] \
                or previousprojectstatus['ref'] != self.projconf["ref"] \
                or previousprojectstatus['sha'] != self.vcs.commitsha:
                self.logger.debug("Returning info that changes found")
                return True
            else:
                self.logger.debug("Returning info of NO changes")
            return False
        else:
            # No configuration means that project has not been compiled
            self.logger.debug("Doing first build of this project")
        return True

    def store_project_status(self):
        """ Save information of the last compilation """
        statusfile = os.path.join(self.project_workspace, 'status.txt')
        self.logger.debug("Updating status file %s", statusfile)

        projectstatus = {"url": self.projconf["url"],
                         "ref": self.projconf["ref"],
                         "spec": self.projconf["spec"],
                         "packageversion": self.packageversion,
                         "sha": self.vcs.commitsha,
                         "project": self.name}

        with open(statusfile, 'w') as outfile:
            json.dump(projectstatus, outfile)

class ProjectError(RpmbuilderError):

    """ Exceptions originating from Project """
    pass
