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
Logging configuration for rpm builder
"""
import logging
import os
import sys

def configure_logging(verbose=False, debugfile="debug.log"):
    """ Logging to screen(console) and file """

    debugfile_dirname = os.path.dirname(debugfile)
    if not os.path.isdir(debugfile_dirname):
        os.mkdir(debugfile_dirname)

    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(levelname)s: %(message)s',
                        filename=debugfile,
                        filemode='w')
    # define a Handler which writes INFO messages or higher to the sys.stderr
    console = logging.StreamHandler(stream=sys.stdout)
    if verbose:
        console.setLevel(logging.DEBUG)
    else:
        console.setLevel(logging.INFO)
    # set a format which is simpler for console use
    formatter = logging.Formatter('%(levelname)s: %(message)s')
    # tell the handler to use this format
    console.setFormatter(formatter)
    # add the handler to the root log
    logging.getLogger('').addHandler(console)
