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

"""For handling rpm related work"""
import logging
import os
import re
import subprocess
from rpmUtils.miscutils import splitFilename

from rpmbuilder.baseerror import RpmbuilderError
from rpmbuilder.executor import Executor


class Specworker(object):
    """ Working with spec files """

    def __init__(self, directory, specfile=None):
        self.logger = logging.getLogger(__name__)
        if specfile:
            if self.__verify_specfile_exists(os.path.join(directory, specfile)):
                self.specfilename = specfile
            else:
                self.logger.critical("Specfile %s not found", specfile)
                raise SpecError("Spec file not found")
        else:
            self.specfilename = self.__locate_spec_file(directory)

        self.specfilefullpath = os.path.join(directory, self.specfilename)

        self.name = ""
        self.version = ""
        self.release = ""
        self.source_files = []
        self.source_file_extension = None
        self.patch_files = []
        self.buildrequires = []
        self.requires = []
        self.packages = []
        self.files = []
        self.spec_globals = {}
        self.read_spec()

    def __str__(self):
        return 'name:%s version:%s' % (self.name, self.version)

    def __getattr__(self, item):
        return self.spec_globals.get(item)

    @staticmethod
    def __locate_spec_file(directory):
        """ Finding spec files from directory """
        logger = logging.getLogger(__name__)
        logger.debug("Searching for spec files under: %s", directory)
        specfile = ''

        for occurence in os.listdir(directory):
            filefullpath = os.path.join(directory, occurence)
            if os.path.isfile(filefullpath) and filefullpath.endswith(".spec"):
                logger.info("Found spec file: %s", occurence)
                if specfile:
                    logger.critical("Project has more than one spec files."
                                    "I don't know which one to use.")
                    raise SpecError("Multiple spec files")
                else:
                    specfile = occurence
        if specfile:
            return specfile
        else:
            raise SpecError("No spec file available")

    def _read_spec_sources(self):
        cmd = ['spectool', '-n', '-S', self.specfilefullpath]
        sources = self._parse_spectool_output(Executor().run(cmd))
        self.source_file_extension = self.__get_source_file_extension(sources[0])
        return sources

    def _read_spec_patches(self):
        cmd = ['spectool', '-n', '-P', self.specfilefullpath]
        return self._parse_spectool_output(Executor().run(cmd))

    def _parse_spectool_output(self, output):
        return [line.split(':', 1)[1].strip() for line in output.splitlines()]

    def _get_package_names(self):
        cmd = ['rpm', '-q', '--qf', '%{NAME}\n', '--specfile', self.specfilefullpath]
        return Executor().run(cmd).splitlines()

    def _get_version(self):
        cmd = ['rpmspec', '-q', '--queryformat', '%{VERSION}\n', self.specfilefullpath]
        return Executor().run(cmd).splitlines()[0]

    def read_spec(self):
        """ Reading spec file values to variables """
        self.logger.debug("Reading spec file %s", self.specfilefullpath)
        self.source_files = self._read_spec_sources()
        self.patch_files = self._read_spec_patches()
        self.packages = self._get_package_names()
        self.name = self.packages[0]
        self.version = self._get_version()

        with open(self.specfilefullpath, 'r') as filep:
            name_found = False
            for line in filep:
                linestripped = line.strip()

                if linestripped.startswith("#") or not linestripped:
                    continue

                if linestripped.lower().startswith("%global"):
                    try:
                        var, val = re.match(r'^%global (\w+) (.+)$', linestripped).groups()
                        self.spec_globals[var] = val
                    except Exception as err:
                        logger = logging.getLogger(__name__)
                        logger.warning(
                            'Failed to parse %global macro "{}" (error: {})'.format(linestripped,
                                                                                    str(err)))

                elif linestripped.lower().startswith("buildrequires:"):
                    self.buildrequires.extend(self.__get_value_from_line(linestripped))

                elif linestripped.lower().startswith("requires:"):
                    self.requires.extend(self.__get_value_from_line(linestripped))

                elif linestripped.lower().startswith("release:"):
                    templist = self.__get_value_from_line(linestripped)
                    self.release = templist[0]

                elif linestripped.lower().startswith("name:"):
                    name_found = True

                elif linestripped.lower().startswith("%package"):
                    if not name_found:
                        self.logger.error(
                            "SPEC file is faulty. Name of the package should be defined before defining subpackages")
                        raise SpecError(
                            "Problem in spec file. Subpackages defined before %packages")

                elif linestripped.lower().startswith("%files"):
                    if name_found:
                        templist = self.__get_package_names_from_line(self.name, linestripped)
                        self.files.extend(templist)
                    else:
                        self.logger.critical(
                            "SPEC file is faulty. Name of the package should be defined before defining subpackages")
                        raise SpecError("Problem in spec file. No %files defined")

        if not self.verify_spec_ok():
            raise SpecError("Inspect file %s" % self.specfilefullpath)
        self.logger.info("Reading spec file done: %s", str(self))

    def verify_spec_ok(self):
        """ Check that spec file contains the necessary building blocks """
        spec_status = True
        if not self.name:
            self.logger.critical("Spec does not have name defined")
            spec_status = False
        if not self.version:
            self.logger.critical("Spec does not contain version")
            spec_status = False
        if not self.release:
            self.logger.critical("Spec does not contain release")
            spec_status = False
        if not self.source_file_extension:
            self.logger.critical(
                "Spec does not define source information with understandable archive method")
            spec_status = False
        return spec_status

    @staticmethod
    def __get_source_file_extension(line):
        """ Read source file archive file end """

        if line.endswith('.tar.gz'):
            return "tar.gz"
        elif line.endswith('.tgz'):
            return "tgz"
        elif line.endswith('.tar'):
            return "tar"
        elif line.endswith('.tar.bz2'):
            return "tar.bz2"
        elif line.endswith('.tar.xz'):
            return "tar.xz"
        elif line.endswith('.zip'):
            return "zip"
        else:
            raise SpecError(
                "Unknown source archive format. Supported are: tar.gz, tgz, tar, tar.bz2, tar.xz, zip")

    @staticmethod
    def __get_value_from_line(line):
        """ Read spec line where values come after double-colon """
        valuelist = []
        linewithgroups = re.search('(.*):(.*)$', line)
        linevalues = linewithgroups.group(2).strip().replace(' ', ',').split(',')
        for linevalue in linevalues:
            valuelist.append(linevalue.strip(' \t\n\r'))
        return valuelist

    @staticmethod
    def __get_package_names_from_line(name, line):
        """ Read spec line where package names are defined """
        linewithgroups = re.search('%(.*) (.*)$', line)
        if linewithgroups:
            value = linewithgroups.group(2).strip(' \t\n\r')
            return [name + '-' + value]
        return [name]

    def __verify_specfile_exists(self, specfile):
        """ Check that the given spec file exists """
        if not specfile.endswith(".spec"):
            self.logger.error("Given specfile %s does not end with .spec prefix", specfile)
            return False

        if os.path.isfile(specfile):
            return True
        self.logger.error("Could not locate specfile %s", specfile)
        return False


class Repotool(object):
    """ Module for handling rpm related functions """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def createrepo(self, directory):
        """ Create a yum repository of the given directory """
        createrepo_executable = "/usr/bin/createrepo"
        createrepocommand = [createrepo_executable, '--update', directory]
        outputfile = os.path.join(directory, 'log.txt')
        with open(outputfile, 'w') as filep:
            try:
                subprocess.check_call(createrepocommand, shell=False, stdout=filep,
                                      stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError:
                self.logger.critical("There was error running createrepo")
                raise RepotoolError("There was error running createrepo")
            except OSError:
                self.logger.error(createrepo_executable + "command not available")
                raise RepotoolError("No createrepo tool available")

    def latest_release_of_package(self, directory, package, version):
        """ Return latest release of the given package """
        self.logger.debug("Looking for latest %s - %s under %s",
                          package, version, directory)
        latest_found_release = 0
        if os.path.isdir(directory):
            for occurence in os.listdir(directory):
                filefullpath = os.path.join(directory, occurence)
                if os.path.isfile(filefullpath) \
                        and filefullpath.endswith(".rpm") \
                        and not filefullpath.endswith(".src.rpm"):
                    (rpmname, rpmversion, rpmrelease, _, _) = splitFilename(occurence)
                    if rpmname == package and rpmversion == version:
                        self.logger.debug("Found rpm " + filefullpath)
                        if latest_found_release < rpmrelease:
                            self.logger.debug("Found rpm to match and to be the latest")
                            latest_found_release = rpmrelease
        if latest_found_release == 0:
            self.logger.debug("Did not find any previous releases of %s", package)
            # try to use Jenkins BUILD_NUMBER
            if "BUILD_NUMBER" in os.environ:
                # next_release_of_package function will increment this release number
                latest_found_release = int(os.environ["BUILD_NUMBER"]) - 1
        return str(latest_found_release)

    def next_release_of_package(self, directory, package, version, oldrelease):
        """ Return next release of the given package """
        self.logger.debug("Looking for next release number for %s - %s under %s ", package, version,
                          directory)

        specreleasematch = re.search('^([0-9]+)(.*)$', oldrelease)
        if specreleasematch and specreleasematch.group(2):
            releasesuffix = specreleasematch.group(2)
        else:
            releasesuffix = ''

        latest_release = self.latest_release_of_package(directory, package, version)
        self.logger.debug("Latest release of the package: " + latest_release)
        rematches = re.search('^([0-9]+)(.*)$', latest_release)
        if rematches.group(1).isdigit():
            nextrelease = str(int(rematches.group(1)) + 1) + releasesuffix
            self.logger.debug("Next release of the package: " + nextrelease)
            return nextrelease
        else:
            self.logger.critical("Could not parse release \"%s\" from package \"%s\"",
                                 latest_release, package)
            raise RepotoolError("Could not process release in rpm")


class RepotoolError(RpmbuilderError):
    """ Exceptions originating from repotool """
    pass


class SpecError(RpmbuilderError):
    """ Exceptions originating from spec content """
    pass
