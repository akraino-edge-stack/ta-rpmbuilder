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

import logging
import subprocess

logger = logging.getLogger(__name__)


class Executor(object):
    def run(self, cmd):
        logger.debug('Executing: {}'.format(cmd))
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        if stderr and p.returncode == 0:
            logger.debug(
                'Command {} exit status {} but stderr not empty: "{}"'.format(cmd, p.returncode,
                                                                              stderr))
        if p.returncode != 0:
            raise Exception('Command {} returned non-zero exit status {}: '
                            'stdout="{}", stderr="{}"'.format(cmd, p.returncode, stdout, stderr))
        return stdout
