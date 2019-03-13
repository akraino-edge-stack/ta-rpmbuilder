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
import os
import re


def find_files(path, pattern=None):
    for root, folders, files in os.walk(path):
        for filename in folders + files:
            if pattern is not None:
                if re.search(pattern, filename):
                    yield os.path.join(root, filename)
            else:
                yield os.path.join(root, filename)
