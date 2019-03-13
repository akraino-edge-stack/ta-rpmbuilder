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

""" Module in charge of building a project """
import glob
import logging
import os
import pwd
import shutil
import subprocess
from distutils.spawn import find_executable

import datetime
from rpmbuilder.baseerror import RpmbuilderError
from rpmbuilder.prettyprinter import Prettyprint

PIGZ_INSTALLED = False
PBZIP2_INSTALLED = False
PXZ_INSTALLED = False

class Packagebuilding(object):

    """ Object for building rpm files with mock """

    def __init__(self, masterargs):
        # Chroothousekeeping cleans chroot in case of mock errors. This should
        # keep /var/lib/mock from growing too much
        self.masterargs = masterargs
        self.logger = logging.getLogger(__name__)
        self.__check_tool_availability()
        self.chroot_installed_rpms = []

        if find_executable("pigz"):
            global PIGZ_INSTALLED
            PIGZ_INSTALLED = True
            self.logger.debug("pigz is available")
        if find_executable("pbzip2"):
            global PBZIP2_INSTALLED
            PBZIP2_INSTALLED = True
            self.logger.debug("pbzip2 is available")
        if find_executable("pxz"):
            global PXZ_INSTALLED
            PXZ_INSTALLED = True
            self.logger.debug("pxz is available")

    @staticmethod
    def __check_tool_availability():
        """ Verify that user belongs to mock group for things to work """
        username = pwd.getpwuid(os.getuid())[0]
        cmd = "id " + username + "| grep \\(mock\\) > /dev/null"
        if os.system(cmd) != 0:
            raise PackagebuildingError("Mock tool requires user to "
                                       "belong to group called mock")
        return True

    def patch_specfile(self, origspecfile, outputdir, newversion, newrelease):
        """ Spec file is patched with version information from git describe """
        Prettyprint().print_heading("Patch spec", 50)
        self.logger.info("Patching new spec from %s", origspecfile)
        self.logger.debug(" - Version: %s", newversion)
        self.logger.debug(" - Release: %s", newrelease)

        specfilebasename = os.path.basename(origspecfile)
        patchedspecfile = os.path.join(outputdir, specfilebasename)
        self.logger.debug("Writing new spec file to %s", patchedspecfile)

        with open(origspecfile, 'r') as filepin:
            filepin_lines = filepin.readlines()

        with open(patchedspecfile, 'w') as filepout:
            for line in filepin_lines:
                linestripped = line.strip()
                if not linestripped.startswith("#"):
                    # Check if version could be patched
                    if linestripped.lower().startswith("version:"):
                        filepout.write("Version: " + newversion + '\n')
                    elif linestripped.lower().startswith("release:"):
                        filepout.write("Release: " + newrelease + '\n')
                    else:
                        filepout.write(line)
        return patchedspecfile

    def init_mock_chroot(self, resultdir, configdir, root):
        """
        Start a mock chroot where build requirements
        can be installed before building
        """
        Prettyprint().print_heading("Mock init in " + root, 50)

        self.clean_directory(resultdir)

        mock_arg_resultdir = "--resultdir=" + resultdir

        mocklogfile = resultdir + '/mock-init-' + root + '.log'

        arguments = [mock_arg_resultdir,
                     "--scrub=all"]
        self.run_mock_command(arguments, mocklogfile, configdir, root)

        #Allow the builder to run sudo without terminal and without password
        #This makes it possible to run disk image builder needed by ipa-builder
        allow_sudo_str = "mockbuild ALL=(ALL) NOPASSWD: ALL"
        notty_str = "Defaults:mockbuild !requiretty"
        sudoers_file = "/etc/sudoers"
        command = "grep \'%s\' %s || echo -e \'%s\n%s\' >> %s" %(allow_sudo_str, sudoers_file, allow_sudo_str, notty_str, sudoers_file)
        arguments=["--chroot",
                   command ]
        self.run_mock_command(arguments, mocklogfile, configdir, root)

        return True

    def restore_local_repository(self, localdir, destdir, configdir, root, logfile):
        """
        Mock copying local yum repository to mock environment so that it can
        be used during building of other RPM packages.
        """
        Prettyprint().print_heading("Restoring local repository", 50)
        arguments = ["--copyin",
                     localdir,
                     destdir]
        self.run_mock_command(arguments, logfile, configdir, root)

    def mock_source_rpm(self, hostsourcedir, specfile, resultdir, configdir, root):
        """ Mock SRPM file which can be used to build rpm """
        Prettyprint().print_heading("Mock source rpm in " + root, 50)
        self.logger.info("Build from:")
        self.logger.info(" - source directory %s", hostsourcedir)
        self.logger.info(" - spec %s", specfile)

        self.clean_directory(resultdir)

        mock_arg_resultdir = "--resultdir=" + resultdir
        mock_arg_spec = "--spec=" + specfile
        mock_arg_sources = "--sources=" + hostsourcedir
        arguments = [mock_arg_resultdir,
                     "--no-clean",
                     "--no-cleanup-after",
                     "--buildsrpm",
                     mock_arg_sources,
                     mock_arg_spec]

        mocklogfile = resultdir + '/mock.log'
        self.run_mock_command(arguments, mocklogfile, configdir, root)

        # Find source rpm and return the path
        globstring = resultdir + '/*.src.rpm'
        globmatches = glob.glob(globstring)
        assert len(globmatches) == 1, "Too many source rpm files"

        return globmatches[0]

    def mock_rpm(self, sourcerpm, resultdir, configdir, root):
        """ Mock RPM binary file from SRPM """
        Prettyprint().print_heading("Mock rpm in " + root, 50)
        self.logger.info("Building from:")
        self.logger.info(" - source rpm %s", sourcerpm)

        self.clean_directory(resultdir)

        mock_arg_resultdir = "--resultdir=" + resultdir
        arguments = [mock_arg_resultdir,
                     "--no-clean",
                     "--no-cleanup-after",
                     "--rebuild",
                     sourcerpm]

        mocklogfile = resultdir + '/mock.log'
        self.run_mock_command(arguments, mocklogfile, configdir, root)

        self.logger.debug("RPM files build to: %s", resultdir)
        return True

    def mock_rpm_from_archive(self, source_tar_packages, resultdir, configdir, root):
        """ Mock rpm binary file straight from archive file """
        self.clean_directory(resultdir)

        # Copy source archive to chroot
        chroot_sourcedir = "/builddir/build/SOURCES/"
        self.copy_to_chroot(configdir, root, resultdir, source_tar_packages, chroot_sourcedir)

        # Create rpm from source archive
        sourcebasename = os.path.basename(source_tar_packages[0])
        chrootsourcefile = os.path.join(chroot_sourcedir, sourcebasename)

        Prettyprint().print_heading("Mock rpm in " + root, 50)
        self.logger.info("Building from:")
        self.logger.info(" - source archive %s", chrootsourcefile)

        mock_arg_resultdir = "--resultdir=" + resultdir
        rpmbuildcommand = "/usr/bin/rpmbuild --noclean -tb -v "
        rpmbuildcommand += os.path.join(chroot_sourcedir, chrootsourcefile)
        arguments = [mock_arg_resultdir,
                     "--chroot",
                     rpmbuildcommand]
        mocklogfile = resultdir + '/mock-rpmbuild.log'
        self.run_mock_command(arguments, mocklogfile, configdir, root)

    def mock_rpm_from_filesystem(self, path, spec, resultdir, configdir, root, srpm_resultdir):
        """ Mock rpm binary file straight from archive file """
        self.clean_directory(resultdir)
        # Copy source archive to chroot
        chroot_sourcedir = "/builddir/build/"
        self.copy_to_chroot(configdir, root, resultdir, [os.path.join(path, 'SPECS', spec)], os.path.join(chroot_sourcedir, 'SPECS'))
        self.copy_to_chroot(configdir, root, resultdir, [os.path.join(path, 'SOURCES', f) for f in os.listdir(os.path.join(path, 'SOURCES'))], os.path.join(chroot_sourcedir, 'SOURCES'))

        Prettyprint().print_heading("Mock rpm in " + root, 50)
        mocklogfile = resultdir + '/mock-rpmbuild.log'
        mock_arg_resultdir = "--resultdir=" + resultdir
        arguments = [mock_arg_resultdir,
                     "--chroot",
                     "chown -R root:root "+chroot_sourcedir]
        self.run_mock_command(arguments, mocklogfile, configdir, root)
        rpmbuildcommand = "/usr/bin/rpmbuild --noclean -ba -v "
        rpmbuildcommand += os.path.join(chroot_sourcedir, 'SPECS', spec)
        arguments = [mock_arg_resultdir,
                     "--chroot",
                     rpmbuildcommand]
        mocklogfile = resultdir + '/mock-rpmbuild.log'
        self.run_mock_command(arguments, mocklogfile, configdir, root)

        arguments = ["--copyout",
                     "/builddir/build", resultdir+"/tmp/packages"]
        mocklogfile = resultdir + '/mock-copyout.log'
        self.run_mock_command(arguments, mocklogfile, configdir, root)

        for filename in glob.glob(resultdir+"/tmp/packages/RPMS/*"):
            shutil.move(filename, resultdir)

        for filename in glob.glob(resultdir+"/tmp/packages/SRPMS/*"):
            shutil.move(filename, srpm_resultdir)

    def mock_wipe_buildroot(self, resultdir, configdir, root):
        """ Wipe buildroot clean """
        Prettyprint().print_heading("Wiping buildroot", 50)
        arguments = ["--chroot",
                     "mkdir -pv /usr/localrepo && " \
                     "cp -v /builddir/build/RPMS/*.rpm /usr/localrepo/. ;" \
                     "rm -rf /builddir/build/{BUILD,RPMS,SOURCES,SPECS,SRPMS}/*"]
        mocklogfile = resultdir + '/mock-wipe-buildroot.log'
        self.run_mock_command(arguments, mocklogfile, configdir, root)

    def update_local_repository(self, configdir, root):
        Prettyprint().print_heading("Update repository " + root, 50)

        arguments = ["--chroot",
                     "mkdir -pv /usr/localrepo && " \
                     "createrepo --update /usr/localrepo && yum clean expire-cache"]
        self.run_mock_command(arguments, configdir+"/log", configdir, root)

    def copy_to_chroot(self, configdir, root, resultdir, source_files, destination):
        # Copy source archive to chroot
        Prettyprint().print_heading("Copy source archive to " + root, 50)
        self.logger.info(" - Copy from %s", source_files)
        self.logger.info(" - Copy to   %s", destination)

        mock_arg_resultdir = "--resultdir=" + resultdir
        arguments = [mock_arg_resultdir,
                     "--copyin"]
        arguments.extend(source_files)
        arguments.append(destination)

        mocklogfile = resultdir + '/mock-copyin.log'
        self.run_mock_command(arguments, mocklogfile, configdir, root)

    def scrub_mock_chroot(self, configdir, root):
        time_start = datetime.datetime.now()
        Prettyprint().print_heading("Scrub mock chroot " + root, 50)
        mock_clean_command = ["/usr/bin/mock",
                              "--configdir=" + configdir,
                              "--root=" + root,
                              "--uniqueext=" + self.masterargs.uniqueext,
                              "--orphanskill",
                              "--scrub=chroot"]
        self.logger.info("Removing mock chroot.")
        self.logger.debug(" ".join(mock_clean_command))
        try:
            subprocess.check_call(mock_clean_command,
                                  shell=False,
                                  stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as err:
            raise PackagebuildingError("Mock chroot removal failed. Error code %s" % (err.returncode))
        time_delta = datetime.datetime.now() - time_start
        self.logger.debug('[mock-end] cmd="%s" took=%s (%s sec)', mock_clean_command, time_delta, time_delta.seconds)

    def run_builddep(self, specfile, resultdir, configdir, root):
        arguments = ["--copyin"]
        arguments.append(specfile)
        arguments.append("/builddir/"+os.path.basename(specfile))

        mocklogfile = resultdir + '/mock-builddep.log'
        self.run_mock_command(arguments, mocklogfile, configdir, root)

        builddepcommand = "/usr/bin/yum-builddep -y "+"/builddir/"+os.path.basename(specfile)
        arguments = ["--chroot",
                     builddepcommand]
        mocklogfile = resultdir + '/mock-builddep.log'
        return self.run_mock_command(arguments, mocklogfile, configdir, root, True) == 0

    def run_mock_command(self, arguments, outputfile, configdir, root, return_error=False):
        """ Mock binary rpm package """
        mock_command = ["/usr/bin/mock",
                        "--configdir=" + configdir,
                        "--root=" + root,
                        "--uniqueext=" + self.masterargs.uniqueext,
                        "--verbose",
                        "--old-chroot",
                        "--enable-network"]
        mock_command.extend(arguments)
        if self.masterargs.mockarguments:
            mock_command.extend([self.masterargs.mockarguments])
        self.logger.info("Running mock. Log goes to %s", outputfile)
        self.logger.debug('[mock-start] cmd="%s"', mock_command)
        time_start = datetime.datetime.now()
        self.logger.debug(" ".join(mock_command))
        with open(outputfile, 'a') as filep:
            try:
                mockproc = subprocess.Popen(mock_command,
                                            shell=False,
                                            stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT)
                for line in iter(mockproc.stdout.readline, b''):
                    if self.masterargs.verbose:
                        self.logger.debug("mock-%s", line.rstrip('\n'))
                    filep.write(line)
                _, stderr = mockproc.communicate()  # wait for the subprocess to exit
                if return_error:
                    return mockproc.returncode
                if mockproc.returncode != 0:
                    raise Mockcommanderror(returncode=mockproc.returncode)
            except Mockcommanderror as err:
                self.logger.error("There was a failure during mocking")
                if self.masterargs.scrub:
                    self.scrub_mock_chroot(configdir, root)
                    guidance_message = ""
                else:
                    mock_shell_command = ["/usr/bin/mock",
                                          "--configdir=" + configdir,
                                          "--root=" + root,
                                          "--uniqueext=" + self.masterargs.uniqueext,
                                          "--shell"]
                    guidance_message = ". To open mock shell, run the following: " + " ".join(mock_shell_command)
                raise PackagebuildingError("Mock exited with value \"%s\". "
                                           "Log for debuging: %s %s" % (err.returncode, outputfile, guidance_message))
            except OSError:
                raise PackagebuildingError("Mock executable not found. "
                                           "Have you installed mock?")
            except:
                raise
        time_delta = datetime.datetime.now() - time_start
        self.logger.debug('[mock-end] cmd="%s" took=%s (%s sec)', mock_command, time_delta, time_delta.seconds)

    def clean_directory(self, directory):
        """ Make sure given directory exists and is clean """
        if os.path.isdir(directory):
            shutil.rmtree(directory)
        os.makedirs(directory)

    def tar_filter(self, tarinfo):
        """ Filter git related and spec files away """
        if tarinfo.name.endswith('.spec') or tarinfo.name.endswith('.git'):
            self.logger.debug("Ignore %s", tarinfo.name)
            return None
        self.logger.debug("Archiving %s", tarinfo.name)
        return tarinfo

    def create_source_archive(self,
                              package_name,
                              sourcedir,
                              outputdir,
                              project_changed,
                              archive_file_extension):
        """
        Create tar file. Example helloworld-2.4.tar.gz
        Tar file has naming <name>-<version>.tar.gz
        """
        Prettyprint().print_heading("Tar package creation", 50)

        tar_file = package_name + '.' + 'tar'
        # Directory where tar should be stored.
        # Example /var/mybuild/workspace/sources

        tarfilefullpath = os.path.join(outputdir, tar_file)
        if os.path.isfile(tarfilefullpath) and not project_changed:
            self.logger.info("Using cached %s", tarfilefullpath)
            return tarfilefullpath

        self.logger.info("Creating tar file %s", tarfilefullpath)
        # sourcedir          = /var/mybuild/helloworld/checkout
        # sourcedir_dirname  = /var/mybuild/helloworld
        # sourcedir_basename =                         checkout
        sourcedir_dirname = os.path.dirname(sourcedir)

        os.chdir(sourcedir_dirname)

        tar_params = ["tar", "cf", tarfilefullpath, "--directory="+os.path.dirname(sourcedir)]
        tar_params = tar_params+["--exclude-vcs"]
        tar_params = tar_params+["--transform=s/" + os.path.basename(sourcedir) + "/" + os.path.join(package_name) + "/"]
        tar_params = tar_params+[os.path.basename(sourcedir)]
        self.logger.debug("Running: %s", " ".join(tar_params))
        ret = subprocess.call(tar_params)
        if ret > 0:
            raise PackagebuildingError("Tar error: %s", ret)

        git_dir = os.path.join(os.path.basename(sourcedir), '.git')
        if os.path.exists(git_dir):
            tar_params = ["tar", "rf", tarfilefullpath, "--directory="+os.path.dirname(sourcedir)]
            tar_params += ["--transform=s/" + os.path.basename(sourcedir) + "/" + os.path.join(package_name) + "/"]
            tar_params += ['--dereference', git_dir]
            self.logger.debug("Running: %s", " ".join(tar_params))
            ret = subprocess.call(tar_params)
            if ret > 1:
                self.logger.warning("Git dir tar failed")

        if archive_file_extension == "tar.gz":
            if PIGZ_INSTALLED:
                cmd = ['pigz', '-f']
            else:
                cmd = ['gzip', '-f']
            resultfile = tarfilefullpath + '.gz'
        else:
            raise PackagebuildingError("Unknown source archive format: %s" % archive_file_extension)
        cmd += [tarfilefullpath]
        self.logger.debug("Running: %s", " ".join(cmd))
        ret = subprocess.call(cmd)
        if ret > 0:
            raise PackagebuildingError("Cmd error: %s", ret)

        return resultfile

class Mockcommanderror(RpmbuilderError):
    def __init__(self, returncode):
        self.returncode = returncode

class PackagebuildingError(RpmbuilderError):

    """ Exceptions originating from Builder and main level """
    pass
