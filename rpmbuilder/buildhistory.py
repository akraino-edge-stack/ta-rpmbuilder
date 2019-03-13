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

""" Writing of history for the build. History explain why different
projects were built at some time. """

import logging
import datetime
import json
import os

class Buildhistory(object):

    """ Build history checks what has been built and
    creates a file using this information """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def update_history(self, outfile, built_projects, projects):
        """ Request history and push it to be written into file """
        history = self.__gather_history(built_projects, projects)
        self.__write_history_txt(outfile + '.log', history)
        self.__write_history_json(outfile + '.json', history)

    def __write_history_txt(self, outfile, history):
        """ Write history to a file """
        self.logger.info("Writing build history to %s", outfile)
        with open(outfile, 'a') as fpoint:
            for change in history:
                fpoint.write(change + '\n')
                for project in history[change]:
                    fpoint.write('  ' + project)
                    if 'commit' in history[change][project]:
                        fpoint.write('  ' + history[change][project]['commit'] + '\n')
                    else:
                        fpoint.write('\n')
                    for rpmfile in history[change][project]['rpmfiles']:
                        fpoint.write('    ' + rpmfile + '\n')
                    for rpmfile in history[change][project]['srpmfiles']:
                        fpoint.write('    ' + rpmfile + '\n')

    def __write_history_json(self, outfile, history):
        """ Write dict history to a file as json """
        self.logger.info("Writing build history to %s", outfile)
        jsondata = {}
        if os.path.isfile(outfile):
            with open(outfile, 'r') as fpoint:
                jsondata = json.load(fpoint)[0]
        jsondata.update(history)
        with open(outfile, 'w') as fpoint:
            fpoint.write(json.dumps([jsondata], indent=2, sort_keys=True) + '\n')

        """ Example of output content
{
  "2018-10-11 08:39:16.918914": {
    "ansible-fm": {
      "rpmfiles": [
        "ansible-fm-c46.gde71b7e-1.el7.centos.noarch.rpm"
      ],
      "commit": "de71b7e7fc0410df3d74cf209f5216b24157988a",
      "srpmfiles": [
        "ansible-fm-c46.gde71b7e-1.el7.centos.src.rpm"
      ]
    }
  }
}
        """

    @staticmethod
    def __gather_history(built_projects, projects):
        """ Loop projects and check what are the versions. This is then history """
        builddate = str(datetime.datetime.now())
        historydict = {builddate: {}} # dict for all projects
        for project in built_projects:
            # Store commit hash version
            commitsha = None
            if projects[project].project_changed and hasattr(projects[project], 'vcs') and projects[project].vcs.commitsha:
                commitsha = projects[project].vcs.commitsha

            # List new rpm files from a project
            rpmfiles = []
            srpmfiles = []
            for buildroot in projects[project].builders.roots:
                (rpmlist, srpmlist) = projects[project].list_buildproducts_for_mockroot(buildroot)
                rpmfiles.extend(rpmlist)
                srpmfiles.extend(srpmlist)
            projectchange = {project: {'rpmfiles': rpmfiles, 'srpmfiles': srpmfiles}}
            if commitsha:
                projectchange[project].update({'commit': commitsha})
            historydict[builddate].update(projectchange)
        return historydict
