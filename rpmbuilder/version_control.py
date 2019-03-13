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
Module for handling git repository clones
"""
import logging
import os
import re
import subprocess
from time import strftime, localtime

from rpmbuilder.baseerror import RpmbuilderError


class VersionControlSystem(object):
    """ Handling of project's repositories """

    def __init__(self, clone_target_dir):
        self.logger = logging.getLogger(__name__)
        self.clone_target_dir = clone_target_dir
        self.citag = None
        self.commitsha = None
        self.commitauth = None
        self.commitepocdate = None
        self.commitmessage = None
        self.describe = None
        try:
            self.__store_head_state()
        except VcsError:
            pass

    def update_git_project(self, url, usergivenref):
        """ Update of a single repository based on given reference """
        self.logger.info("%-18s: %s", "Git cloning from", url)
        self.logger.info("%-18s: %s", "Git cloning to", self.clone_target_dir)
        self.logger.info("%-18s: %s", "Git reference", usergivenref)

        # Check if we already have local clone of the repository
        self.__clone_repo(url)

        # Change to user given ref value.
        self.__update_head(url, usergivenref)

        self.__store_head_state()
        self.citag = self.get_citag()

    def __clone_repo(self, url):
        """ Create a clone from URL. If already exists, update it """
        if not os.path.isdir(self.clone_target_dir):
            self.logger.debug("Creating a fresh clone")
            cmd = ['git', 'clone', url, self.clone_target_dir]
            self.logger.debug(self.__run_git(cmd))
        else:
            self.logger.debug("We already have a clone. Using old clone.")
            # Remove any possible garbage from clone directory
            self.logger.debug("Running cleaning of existing repository")
            cmd = ['git', 'reset', '--hard']
            self.logger.debug(self.__run_git(cmd, self.clone_target_dir))
            # Verify that correct remote is being used
            self.__set_remoteurl(url)
            # Run fetch twice. From Git 1.9 onwards this is not necessary,
            # but to make sure of all server compatibility we do it twice
            self.logger.debug("Fetching latest from remote")
            cmd = ['git', 'fetch', 'origin']
            self.logger.debug(self.__run_git(cmd, self.clone_target_dir))
            cmd = ['git', 'fetch', 'origin', '--tags']
            self.logger.debug(self.__run_git(cmd, self.clone_target_dir))

    def __update_head(self, url, usergivenref):
        """ Change head to point to given ref. Ref can also be tag/commit """
        self.logger.debug("Reseting git head to %s", usergivenref)
        try:
            self.logger.debug("Checking out %s as reference", usergivenref)
            cmd = ['git', 'checkout', '--force', '--detach', 'origin/' + usergivenref]
            self.logger.debug(self.__run_git(cmd, self.clone_target_dir))
        except:
            self.logger.debug("Unable to checkout %s as reference", usergivenref)
            try:
                self.logger.debug("Checking out %s as tag/commit", usergivenref)
                cmd = ['git', 'checkout', '--force', '--detach', usergivenref]
                self.logger.debug(self.__run_git(cmd, self.clone_target_dir))
            except GitError:
                raise VcsError(
                    "Could not checkout branch/ref/commit \"%s\" from %s." % (usergivenref, url))

    def __run_git(self, gitcmd, gitcwd=None):
        """ Run given git command """
        assert gitcmd
        self.logger.debug("Running \'%s\' under directory %s", " ".join(gitcmd), gitcwd)
        try:
            return subprocess.check_output(gitcmd,
                                           shell=False,
                                           cwd=gitcwd)
        except subprocess.CalledProcessError as err:
            raise GitError("Could not execute %s command. Return code was %d" % (err.cmd,
                                                                                 err.returncode))
        except:
            raise

    def __set_remoteurl(self, url):
        """
        Verify that repository is using the correct remote URL. If not
        then it should be changed to the desired one.
        """
        self.logger.info("Verifying we have correct remote repository configured")
        cmd = ["git", "config", "--get", "remote.origin.url"]
        existing_clone_url = self.__run_git(cmd, self.clone_target_dir).strip()
        if existing_clone_url != url:
            self.logger.info("Existing repo has url: %s", existing_clone_url)
            self.logger.info("Changing repo url to: %s", url)
            cmd = ["git", "remote", "set-url", "origin", url]
            self.logger.debug(self.__run_git(cmd, self.clone_target_dir))

    def __store_head_state(self):
        """ Read checkout values to be used elsewhere """
        self.logger.info("State of the checkout:")

        try:
            cmd = ["git", "log", "-1", "--pretty=%H"]
            self.commitsha = self.__run_git(cmd, self.clone_target_dir).strip()
            self.logger.info("  %-10s: %s", "SHA", self.commitsha)

            cmd = ["git", "log", "-1", "--pretty=%ae"]
            self.commitauth = self.__run_git(cmd, self.clone_target_dir).strip()
            self.logger.info("  %-10s: %s", "Author", self.commitauth)

            cmd = ["git", "log", "-1", "--pretty=%ct"]
            self.commitepocdate = float(self.__run_git(cmd, self.clone_target_dir).strip())
            self.logger.info("  %-10s: %s", "Date:",
                             strftime("%a, %d %b %Y %H:%M:%S",
                                      localtime(self.commitepocdate)))

            cmd = ["git", "log", "-1", "--pretty=%B"]
            self.commitmessage = self.__run_git(cmd, self.clone_target_dir).strip()
            self.logger.info("  %-10s: %s", "Message:", self.commitmessage.split('\n', 1)[0])
        except GitError:
            raise VcsError("Directory \"%s\" does not come from vcs" % self.clone_target_dir)

    def is_dirty(self):
        """ Check the status of directory. Return true if version control is dirty.
        Git clone is dirty if status shows anything """
        cmd = ["git", "status", "--porcelain"]
        return len(self.__run_git(cmd, self.clone_target_dir).strip()) > 0

    def get_citag(self):
        """ This is for creating the tag for the rpm. """

        if self.citag:
            return self.citag

        setup_py = os.path.join(self.clone_target_dir, 'setup.py')
        if os.path.exists(setup_py):
            with open(setup_py, 'r') as fpoint:
                if re.search(r'^.*setup_requires=.*pbr.*$', fpoint.read(), re.MULTILINE):
                    cmd = ['python', 'setup.py', '--version']
                    citag = self.__run_git(cmd, self.clone_target_dir).strip()
                    if ' ' in citag or '\n' in citag:
                        # 1st execution output may contains extra stuff such as locally installed eggs
                        citag = self.__run_git(cmd, self.clone_target_dir).strip()
                    return citag

        try:
            cmd = ["git", "describe", "--dirty", "--tags"]
            describe = self.__run_git(cmd, self.clone_target_dir).strip()
            self.logger.debug("Git describe from tags: %s", describe)
            if re.search("-", describe):
                # if describe format is 2.3-3-g4324323, we need to modify it
                dmatch = re.match('^(.*)-([0-9]+)-(g[a-f0-9]{7,}).*$', describe)
                if dmatch:
                    citag = describe.replace('-', '-c', 1)
                else:
                    raise Exception('no match, falling back to non-tagged describe')
            else:
                # if describe format is 2.3
                citag = describe
        except:
            try:
                count = self.__run_git(["git", "rev-list", "HEAD", "--count"],
                                       self.clone_target_dir).strip()
                sha = self.__run_git(["git", "describe", "--long", "--always"],
                                     self.clone_target_dir).strip()
                citag = 'c{}.g{}'.format(count, sha)
            except:
                raise VcsError("Could not create a name for the package with git describe")
        # Replace all remaining '-' characters with '.' from version number
        if re.search("-", citag):
            citag = re.sub('-', '.', citag)
        return citag


class VcsError(RpmbuilderError):
    """ Exceptions for all version control error situations """
    pass


class GitError(RpmbuilderError):
    """ Exceptions for git command errors """
    pass
