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

import re
import mock
import pytest

from rpmbuilder.executor import Executor


@pytest.mark.parametrize('input_cmd, expected_output', [
    (['true'], ''),
    (['echo', 'foo'], 'foo\n'),
])
def test_run_cmd(input_cmd, expected_output):
    assert Executor().run(input_cmd) == expected_output


@mock.patch('logging.Logger.debug')
@mock.patch('subprocess.Popen')
def test_stderr_is_logged(mock_popen, mock_log):
    process_mock = mock.Mock()
    process_mock.configure_mock(**{
        'communicate.return_value': ('some ouput', 'some errput'),
        'returncode': 0,
    })
    mock_popen.return_value = process_mock
    Executor().run(['ls'])
    assert re.match('.*exit status 0 but stderr not empty.*', mock_log.call_args[0][0])


def test_run_cmd_fail():
    err_regexp = 'Command .* returned non-zero exit status 2: stdout="", ' \
                 'stderr="ls: .* No such file or directory'
    with pytest.raises(Exception,
                       match=err_regexp):
        Executor().run(['ls', 'bar'])
